"""Tests for the in-memory job store."""

from __future__ import annotations

import pytest

from app.models.job import JobStatus
from app.services.job_store import InMemoryJobStore


@pytest.fixture()
def store() -> InMemoryJobStore:
    return InMemoryJobStore()


def test_create_and_get(store: InMemoryJobStore):
    state = store.create("job-1")
    assert state.job_id == "job-1"
    assert state.status == JobStatus.PENDING
    assert state.progress == 0.0

    fetched = store.get("job-1")
    assert fetched is not None
    assert fetched.job_id == "job-1"


def test_get_missing(store: InMemoryJobStore):
    assert store.get("nonexistent") is None


def test_update_status(store: InMemoryJobStore):
    store.create("j")
    updated = store.update("j", status=JobStatus.PROCESSING, progress=0.5, message="half-way")
    assert updated.status == JobStatus.PROCESSING
    assert updated.progress == 0.5
    assert updated.message == "half-way"

    # Verify persistence
    assert store.get("j").status == JobStatus.PROCESSING


def test_update_clamps_progress(store: InMemoryJobStore):
    store.create("j")
    store.update("j", progress=1.5)
    assert store.get("j").progress == 1.0

    store.update("j", progress=-0.3)
    assert store.get("j").progress == 0.0


def test_update_done_with_output(store: InMemoryJobStore):
    store.create("j")
    store.update("j", status=JobStatus.DONE, output_path="/tmp/out.pdf", progress=1.0)
    state = store.get("j")
    assert state.status == JobStatus.DONE
    assert state.output_path == "/tmp/out.pdf"


def test_update_failed_with_error(store: InMemoryJobStore):
    store.create("j")
    store.update("j", status=JobStatus.FAILED, error="OOM", message="Generation failed")
    state = store.get("j")
    assert state.status == JobStatus.FAILED
    assert state.error == "OOM"


def test_thread_safety(store: InMemoryJobStore):
    """Create many jobs from multiple threads — no race conditions expected."""
    import threading

    errors: list[Exception] = []
    results: list[str] = []

    def worker(i: int) -> None:
        try:
            jid = f"job-{i}"
            store.create(jid)
            store.update(jid, progress=0.5)
            state = store.get(jid)
            assert state is not None
            results.append(jid)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 50
