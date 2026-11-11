"""Tests for GET /download/{id}."""

from __future__ import annotations

import pytest

from app.db.models import Job, JobStatus
from tests.conftest import HEADERS, make_pdf_bytes


def test_download_done_job(client, done_job):
    r = client.get(f"/download/{done_job.id}", headers=HEADERS)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert len(r.content) > 0


def test_download_filename_header(client, done_job):
    r = client.get(f"/download/{done_job.id}", headers=HEADERS)
    assert done_job.id in r.headers.get("content-disposition", "")


def test_download_not_found(client):
    r = client.get("/download/no-such-job", headers=HEADERS)
    assert r.status_code == 404


def test_download_queued_job_returns_409(client, db_session, ready_profile, tmp_path):
    j = Job(
        id="queued-dl",
        profile_id=ready_profile.id,
        input_pdf_path=str(tmp_path / "in.pdf"),
        status=JobStatus.QUEUED,
        progress=0.0,
        message="Queued",
    )
    db_session.add(j)
    db_session.commit()

    r = client.get("/download/queued-dl", headers=HEADERS)
    assert r.status_code == 409


def test_download_processing_job_returns_409(client, db_session, ready_profile, tmp_path):
    j = Job(
        id="proc-dl",
        profile_id=ready_profile.id,
        input_pdf_path=str(tmp_path / "in.pdf"),
        status=JobStatus.PROCESSING,
        progress=0.5,
        message="Working",
    )
    db_session.add(j)
    db_session.commit()

    r = client.get("/download/proc-dl", headers=HEADERS)
    assert r.status_code == 409


def test_download_failed_job_returns_409(client, db_session, ready_profile, tmp_path):
    j = Job(
        id="failed-dl",
        profile_id=ready_profile.id,
        input_pdf_path=str(tmp_path / "in.pdf"),
        status=JobStatus.FAILED,
        progress=0.0,
        message="Failed",
        error="OOM",
    )
    db_session.add(j)
    db_session.commit()

    r = client.get("/download/failed-dl", headers=HEADERS)
    assert r.status_code == 409


def test_download_missing_file_returns_409(client, db_session, ready_profile, tmp_path):
    """Output path recorded in DB but file has since been deleted."""
    j = Job(
        id="ghost-dl",
        profile_id=ready_profile.id,
        input_pdf_path=str(tmp_path / "in.pdf"),
        output_pdf_path=str(tmp_path / "nonexistent.pdf"),  # doesn't exist
        status=JobStatus.DONE,
        progress=1.0,
        message="Done",
    )
    db_session.add(j)
    db_session.commit()

    r = client.get("/download/ghost-dl", headers=HEADERS)
    assert r.status_code == 409
