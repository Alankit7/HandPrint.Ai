"""Background worker that runs profile fine-tuning.

Flow
----
1. Fetch profile from DB, mark it TRAINING.
2. Call ``ml.stubs.train_profile`` (raises NotImplementedError until real code
   is plugged in) with a progress callback that writes back to the DB.
3. On success: set status=READY, checkpoint_path.
4. On failure: set status=FAILED, store error message.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.db.models import Profile, ProfileStatus
from app.db.session import get_db_ctx
from app.ml.stubs import train_profile

logger = logging.getLogger(__name__)


def run_training(profile_id: str) -> None:
    """Entry point called by the thread pool — never raises."""
    logger.info("[train] Starting training for profile %s", profile_id)

    # ── 1. Mark TRAINING ──────────────────────────────────────────────────────
    with get_db_ctx() as db:
        profile: Profile | None = db.get(Profile, profile_id)
        if profile is None:
            logger.error("[train] Profile %s not found — aborting.", profile_id)
            return
        profile.status = ProfileStatus.TRAINING
        profile.train_progress = 0.0
        profile.error = None

    # ── 2. Prepare checkpoint output directory ────────────────────────────────
    checkpoint_out = settings.output_dir / "checkpoints" / profile_id
    checkpoint_out.mkdir(parents=True, exist_ok=True)

    sample_dir = Path(profile.sample_dir) if profile.sample_dir else None
    if sample_dir is None or not sample_dir.exists():
        _fail(profile_id, "Sample directory missing or inaccessible.")
        return

    # ── 3. Progress callback (writes to DB) ───────────────────────────────────
    def _progress(pct: float) -> None:
        with get_db_ctx() as db:
            p: Profile | None = db.get(Profile, profile_id)
            if p:
                p.train_progress = max(0.0, min(1.0, pct))
        logger.debug("[train] profile=%s progress=%.1f%%", profile_id, pct * 100)

    # ── 4. Run ML stub ────────────────────────────────────────────────────────
    try:
        train_profile(
            profile_id=profile_id,
            sample_dir=sample_dir,
            checkpoint_out_dir=checkpoint_out,
            progress_cb=_progress,
        )
    except NotImplementedError as exc:
        # Stub not yet replaced — treat as a known transient failure
        logger.warning("[train] ML stub not implemented: %s", exc)
        _fail(profile_id, str(exc))
        return
    except Exception as exc:
        logger.exception("[train] Training failed for profile %s: %s", profile_id, exc)
        _fail(profile_id, str(exc))
        return

    # ── 5. Mark READY ─────────────────────────────────────────────────────────
    with get_db_ctx() as db:
        p: Profile | None = db.get(Profile, profile_id)
        if p:
            p.status = ProfileStatus.READY
            p.train_progress = 1.0
            p.checkpoint_path = str(checkpoint_out)
            logger.info("[train] Profile %s is READY.", profile_id)


def _fail(profile_id: str, error: str) -> None:
    with get_db_ctx() as db:
        p: Profile | None = db.get(Profile, profile_id)
        if p:
            p.status = ProfileStatus.FAILED
            p.error = error
            p.train_progress = 0.0
    logger.error("[train] Profile %s FAILED: %s", profile_id, error)
