"""Tests for GET /jobs/{id}."""

from __future__ import annotations

import pytest

from app.db.models import Job, JobStatus
from tests.conftest import HEADERS, make_pdf_bytes


def test_get_job_success(client, done_job):
    r = client.get(f"/jobs/{done_job.id}", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == done_job.id
    assert body["status"] == "done"
    assert body["progress"] == 1.0


def test_get_job_not_found(client):
    r = client.get("/jobs/no-such-job", headers=HEADERS)
    assert r.status_code == 404


def test_job_response_fields(client, done_job):
    r = client.get(f"/jobs/{done_job.id}", headers=HEADERS)
    body = r.json()
    for field in ("id", "profile_id", "status", "progress", "message", "created_at", "updated_at"):
        assert field in body, f"Missing field: {field}"


def test_queued_job_has_zero_progress(client, db_session, ready_profile, tmp_path):
    j = Job(
        id="q-job",
        profile_id=ready_profile.id,
        input_pdf_path=str(tmp_path / "in.pdf"),
        status=JobStatus.QUEUED,
        progress=0.0,
        message="Queued",
    )
    db_session.add(j)
    db_session.commit()

    r = client.get("/jobs/q-job", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["progress"] == 0.0
    assert r.json()["status"] == "queued"


def test_failed_job_has_error(client, db_session, ready_profile, tmp_path):
    j = Job(
        id="fail-job",
        profile_id=ready_profile.id,
        input_pdf_path=str(tmp_path / "in.pdf"),
        status=JobStatus.FAILED,
        progress=0.0,
        message="Failed",
        error="Something went wrong",
    )
    db_session.add(j)
    db_session.commit()

    r = client.get("/jobs/fail-job", headers=HEADERS)
    assert r.json()["status"] == "failed"
    assert r.json()["error"] == "Something went wrong"
