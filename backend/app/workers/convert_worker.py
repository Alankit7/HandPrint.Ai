"""Background worker that runs PDF conversion for a job.

Flow
----
1. Fetch job + profile from DB, mark job PROCESSING.
2. Validate the profile is READY and checkpoint exists.
3. Call ``ml.stubs.render_pdf`` with a progress callback.
4. On success: set status=DONE, output_pdf_path.
5. On failure: set status=FAILED, store error message.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.db.models import Job, JobStatus, Profile, ProfileStatus
from app.db.session import get_db_ctx
from app.ml.stubs import render_pdf

logger = logging.getLogger(__name__)


def run_conversion(job_id: str) -> None:
    """Entry point called by the thread pool — never raises."""
    logger.info("[convert] Starting job %s", job_id)

    # ── 1. Mark PROCESSING ────────────────────────────────────────────────────
    profile_id: str | None = None
    input_pdf: str | None = None
    checkpoint_path: str | None = None

    with get_db_ctx() as db:
        job: Job | None = db.get(Job, job_id)
        if job is None:
            logger.error("[convert] Job %s not found — aborting.", job_id)
            return

        profile: Profile | None = db.get(Profile, job.profile_id)
        if profile is None or profile.status != ProfileStatus.READY:
            _fail(job_id, "Profile is not READY.")
            return

        job.status = JobStatus.PROCESSING
        job.progress = 0.0
        job.message = "Rendering…"
        job.error = None

        profile_id = job.profile_id
        input_pdf = job.input_pdf_path
        checkpoint_path = profile.checkpoint_path

    if not checkpoint_path or not Path(checkpoint_path).exists():
        _fail(job_id, "Checkpoint path missing or inaccessible.")
        return

    # ── 2. Output path ────────────────────────────────────────────────────────
    output_pdf = settings.output_dir / f"{job_id}.pdf"
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    # ── 3. Progress callback ──────────────────────────────────────────────────
    def _progress(pct: float) -> None:
        with get_db_ctx() as db:
            j: Job | None = db.get(Job, job_id)
            if j:
                j.progress = max(0.0, min(1.0, pct))
                j.message = f"Rendering… {int(pct * 100)}%"
        logger.debug("[convert] job=%s progress=%.1f%%", job_id, pct * 100)

    # ── 4. Run ML stub ────────────────────────────────────────────────────────
    try:
        render_pdf(
            input_pdf_path=Path(input_pdf),
            checkpoint_path=Path(checkpoint_path),
            output_pdf_path=output_pdf,
            progress_cb=_progress,
        )
    except NotImplementedError as exc:
        logger.warning("[convert] ML stub not implemented: %s", exc)
        _fail(job_id, str(exc))
        return
    except Exception as exc:
        logger.exception("[convert] Job %s failed: %s", job_id, exc)
        _fail(job_id, str(exc))
        return

    # ── 5. Mark DONE ──────────────────────────────────────────────────────────
    with get_db_ctx() as db:
        j: Job | None = db.get(Job, job_id)
        if j:
            j.status = JobStatus.DONE
            j.progress = 1.0
            j.message = "Done"
            j.output_pdf_path = str(output_pdf)
            logger.info("[convert] Job %s DONE → %s", job_id, output_pdf)


def _fail(job_id: str, error: str) -> None:
    with get_db_ctx() as db:
        j: Job | None = db.get(Job, job_id)
        if j:
            j.status = JobStatus.FAILED
            j.error = error
            j.message = "Failed"
    logger.error("[convert] Job %s FAILED: %s", job_id, error)
