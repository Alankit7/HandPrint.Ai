"""Tests for POST /convert."""

from __future__ import annotations

import pytest

from app.db.models import Profile, ProfileStatus
from tests.conftest import HEADERS, make_pdf_bytes, make_png_bytes


def test_convert_success(client, ready_profile):
    r = client.post(
        "/convert",
        data={"profile_id": ready_profile.id},
        files={"pdf": ("test.pdf", make_pdf_bytes(), "application/pdf")},
        headers=HEADERS,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert "id" in body
    assert body["status"] == "queued"
    assert body["profile_id"] == ready_profile.id


def test_convert_nonexistent_profile(client):
    r = client.post(
        "/convert",
        data={"profile_id": "no-such"},
        files={"pdf": ("t.pdf", make_pdf_bytes(), "application/pdf")},
        headers=HEADERS,
    )
    assert r.status_code == 404


def test_convert_profile_not_ready(client, db_session):
    p = Profile(
        id="pending-profile",
        name="Pending",
        status=ProfileStatus.PENDING,
        sample_count=1,
    )
    db_session.add(p)
    db_session.commit()

    r = client.post(
        "/convert",
        data={"profile_id": "pending-profile"},
        files={"pdf": ("t.pdf", make_pdf_bytes(), "application/pdf")},
        headers=HEADERS,
    )
    assert r.status_code == 409


def test_convert_wrong_file_type(client, ready_profile):
    r = client.post(
        "/convert",
        data={"profile_id": ready_profile.id},
        files={"pdf": ("image.png", make_png_bytes(), "image/png")},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_convert_pdf_too_large(client, ready_profile, monkeypatch):
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "max_pdf_bytes", 1)
    r = client.post(
        "/convert",
        data={"profile_id": ready_profile.id},
        files={"pdf": ("big.pdf", make_pdf_bytes(), "application/pdf")},
        headers=HEADERS,
    )
    assert r.status_code == 413


def test_convert_missing_pdf(client, ready_profile):
    r = client.post(
        "/convert",
        data={"profile_id": ready_profile.id},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_convert_missing_profile_id(client, ready_profile):
    r = client.post(
        "/convert",
        files={"pdf": ("t.pdf", make_pdf_bytes(), "application/pdf")},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_convert_worker_marks_failed_on_stub(client, db_session, ready_profile, tmp_path):
    """Verify the convert worker catches NotImplementedError and sets FAILED."""
    from app.db.models import Job, JobStatus
    from app.workers.convert_worker import run_conversion
    from contextlib import contextmanager
    import app.workers.convert_worker as cw_mod

    # Input PDF must exist on disk for the worker path check to pass
    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(make_pdf_bytes())

    job = Job(
        id="worker-convert-test",
        profile_id=ready_profile.id,
        input_pdf_path=str(input_pdf),
        status=JobStatus.QUEUED,
        message="Queued",
        progress=0.0,
    )
    db_session.add(job)
    db_session.commit()

    @contextmanager
    def _fake_ctx():
        yield db_session

    original = cw_mod.get_db_ctx
    cw_mod.get_db_ctx = _fake_ctx
    try:
        run_conversion("worker-convert-test")
    finally:
        cw_mod.get_db_ctx = original

    db_session.expire_all()
    j = db_session.get(Job, "worker-convert-test")
    assert j.status == JobStatus.FAILED
    assert j.error is not None
