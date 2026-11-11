"""Tests for POST /profiles/{id}/train."""

from __future__ import annotations

import pytest

from app.db.models import Profile, ProfileStatus
from tests.conftest import HEADERS, upload_files_for_profile


def _create_profile(client) -> str:
    files = upload_files_for_profile(n=1)
    r = client.post("/profiles", data={"name": "Trainer"}, files=files, headers=HEADERS)
    assert r.status_code == 201
    return r.json()["id"]


def test_train_enqueues_successfully(client):
    pid = _create_profile(client)
    r = client.post(f"/profiles/{pid}/train", headers=HEADERS)
    assert r.status_code == 202, r.text
    assert "Training started" in r.json()["message"]


def test_train_nonexistent_profile(client):
    r = client.post("/profiles/no-such-id/train", headers=HEADERS)
    assert r.status_code == 404


def test_train_already_training_returns_409(client, db_session):
    """A profile in TRAINING status should reject a second train request."""
    p = Profile(
        id="training-profile",
        name="Busy",
        status=ProfileStatus.TRAINING,
        sample_count=1,
        train_progress=0.3,
    )
    db_session.add(p)
    db_session.commit()

    r = client.post("/profiles/training-profile/train", headers=HEADERS)
    assert r.status_code == 409


def test_train_ready_profile_returns_409(client, ready_profile):
    r = client.post(f"/profiles/{ready_profile.id}/train", headers=HEADERS)
    assert r.status_code == 409


def test_train_failed_profile_allowed(client, db_session):
    """A FAILED profile should be re-trainable."""
    p = Profile(
        id="failed-profile",
        name="Retry",
        status=ProfileStatus.FAILED,
        sample_count=1,
        train_progress=0.0,
        error="OOM",
    )
    db_session.add(p)
    db_session.commit()

    r = client.post("/profiles/failed-profile/train", headers=HEADERS)
    assert r.status_code == 202


def test_train_worker_marks_failed_on_stub(client, db_session, tmp_path):
    """
    Directly invoke the worker function to verify it catches NotImplementedError
    and transitions the profile to FAILED.
    """
    from app.workers.train_worker import run_training
    from app.db.session import get_db_ctx

    # Create profile with valid sample_dir
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    p = Profile(
        id="worker-test-profile",
        name="Worker Test",
        status=ProfileStatus.PENDING,
        sample_count=1,
        sample_dir=str(sample_dir),
    )
    db_session.add(p)
    db_session.commit()

    # Patch get_db_ctx to use our test session
    import app.workers.train_worker as tw_mod
    from contextlib import contextmanager

    @contextmanager
    def _fake_ctx():
        yield db_session

    original = tw_mod.get_db_ctx
    tw_mod.get_db_ctx = _fake_ctx
    try:
        run_training("worker-test-profile")
    finally:
        tw_mod.get_db_ctx = original

    db_session.expire_all()
    profile = db_session.get(Profile, "worker-test-profile")
    assert profile.status == ProfileStatus.FAILED
    assert "NotImplementedError" in profile.error or "stub" in profile.error.lower()
