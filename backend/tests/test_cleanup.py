"""Tests for the cleanup task."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db.models import Job, JobStatus, Profile, ProfileStatus
from app.workers.cleanup import run_cleanup


def _old_dt() -> datetime:
    """A timestamp old enough to be cleaned up (> CLEANUP_AGE_HOURS ago)."""
    return datetime.now(timezone.utc) - timedelta(hours=48)


def test_cleanup_removes_done_job_files(db_session, tmp_path, monkeypatch):
    """Files for DONE jobs older than cutoff are deleted."""
    import app.workers.cleanup as cl
    import app.db.session as sess_mod
    from contextlib import contextmanager

    # Build real files
    in_pdf = tmp_path / "in.pdf"
    out_pdf = tmp_path / "out.pdf"
    in_pdf.write_bytes(b"fake")
    out_pdf.write_bytes(b"fake")

    p = Profile(id="p-cleanup", name="X", status=ProfileStatus.READY, sample_count=1)
    db_session.add(p)

    j = Job(
        id="j-cleanup-done",
        profile_id="p-cleanup",
        input_pdf_path=str(in_pdf),
        output_pdf_path=str(out_pdf),
        status=JobStatus.DONE,
        progress=1.0,
        message="Done",
    )
    # Force old timestamp
    j.updated_at = _old_dt()
    db_session.add(j)
    db_session.commit()

    @contextmanager
    def _fake_ctx():
        yield db_session

    original = cl.get_db_ctx
    cl.get_db_ctx = _fake_ctx
    try:
        run_cleanup()
    finally:
        cl.get_db_ctx = original

    assert not in_pdf.exists(), "Input PDF should have been deleted"
    assert not out_pdf.exists(), "Output PDF should have been deleted"


def test_cleanup_removes_failed_profile_sample_dir(db_session, tmp_path):
    """Sample directory for FAILED profiles older than cutoff is removed."""
    import app.workers.cleanup as cl
    from contextlib import contextmanager

    sample_dir = tmp_path / "samples" / "fail-profile"
    sample_dir.mkdir(parents=True)
    (sample_dir / "img.png").write_bytes(b"fake")

    p = Profile(
        id="fail-cleanup-profile",
        name="Fail",
        status=ProfileStatus.FAILED,
        sample_count=1,
        sample_dir=str(sample_dir),
    )
    p.updated_at = _old_dt()
    db_session.add(p)
    db_session.commit()

    @contextmanager
    def _fake_ctx():
        yield db_session

    original = cl.get_db_ctx
    cl.get_db_ctx = _fake_ctx
    try:
        run_cleanup()
    finally:
        cl.get_db_ctx = original

    assert not sample_dir.exists(), "Sample dir for failed profile should be deleted"


def test_cleanup_skips_recent_jobs(db_session, tmp_path):
    """Files for recent jobs (within cutoff) are NOT deleted."""
    import app.workers.cleanup as cl
    from contextlib import contextmanager

    out_pdf = tmp_path / "recent_out.pdf"
    out_pdf.write_bytes(b"keep me")

    p = Profile(id="p-recent", name="Recent", status=ProfileStatus.READY, sample_count=1)
    db_session.add(p)

    j = Job(
        id="j-recent",
        profile_id="p-recent",
        input_pdf_path=str(tmp_path / "in.pdf"),
        output_pdf_path=str(out_pdf),
        status=JobStatus.DONE,
        progress=1.0,
        message="Done",
    )
    # updated_at defaults to now — well within cutoff
    db_session.add(j)
    db_session.commit()

    @contextmanager
    def _fake_ctx():
        yield db_session

    original = cl.get_db_ctx
    cl.get_db_ctx = _fake_ctx
    try:
        run_cleanup()
    finally:
        cl.get_db_ctx = original

    assert out_pdf.exists(), "Recent output PDF should NOT be deleted"


def test_cleanup_never_raises(db_session):
    """run_cleanup() must swallow all errors (called by scheduler)."""
    import app.workers.cleanup as cl
    from contextlib import contextmanager

    @contextmanager
    def _broken_ctx():
        raise RuntimeError("DB is down")
        yield  # unreachable

    original = cl.get_db_ctx
    cl.get_db_ctx = _broken_ctx
    try:
        run_cleanup()  # must not raise
    finally:
        cl.get_db_ctx = original
