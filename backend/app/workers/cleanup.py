"""Periodic cleanup task.

Removes:
  - Uploaded PDFs whose job is DONE or FAILED and older than CLEANUP_AGE_HOURS.
  - Output PDFs for jobs older than CLEANUP_AGE_HOURS.
  - Sample image directories for profiles older than CLEANUP_AGE_HOURS
    whose status is FAILED.

The scheduler is set up in ``app/main.py`` via APScheduler and calls
``run_cleanup()`` on a fixed interval.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.models import Job, JobStatus, Profile, ProfileStatus
from app.db.session import get_db_ctx

logger = logging.getLogger(__name__)


def run_cleanup() -> None:
    """Delete stale files.  Called by the scheduler — never raises."""
    try:
        _cleanup()
    except Exception as exc:
        logger.exception("Cleanup task failed: %s", exc)


def _cleanup() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.cleanup_age_hours)
    removed_files = 0
    removed_dirs = 0

    with get_db_ctx() as db:
        # ── Stale jobs ────────────────────────────────────────────────────────
        stale_jobs = db.scalars(
            select(Job).where(
                Job.status.in_([JobStatus.DONE, JobStatus.FAILED]),
                Job.updated_at < cutoff,
            )
        ).all()

        for job in stale_jobs:
            # Remove uploaded source PDF
            if job.input_pdf_path:
                p = Path(job.input_pdf_path)
                if p.exists():
                    p.unlink()
                    removed_files += 1
                    logger.debug("Deleted input PDF: %s", p)

            # Remove output PDF
            if job.output_pdf_path:
                p = Path(job.output_pdf_path)
                if p.exists():
                    p.unlink()
                    removed_files += 1
                    logger.debug("Deleted output PDF: %s", p)

        # ── Failed / stale profiles ───────────────────────────────────────────
        stale_profiles = db.scalars(
            select(Profile).where(
                Profile.status == ProfileStatus.FAILED,
                Profile.updated_at < cutoff,
            )
        ).all()

        for profile in stale_profiles:
            if profile.sample_dir:
                d = Path(profile.sample_dir)
                if d.exists() and d.is_dir():
                    shutil.rmtree(d, ignore_errors=True)
                    removed_dirs += 1
                    logger.debug("Deleted sample dir: %s", d)

    logger.info(
        "Cleanup done — removed %d file(s), %d directory(s).",
        removed_files,
        removed_dirs,
    )
