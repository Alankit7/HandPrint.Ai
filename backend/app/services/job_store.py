"""Thread-safe in-process job store (default) with optional Redis backend.

For production with multiple workers, set QUEUE_BACKEND=redis and all state
is serialised as JSON inside Redis hashes.
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.models.job import JobState, JobStatus

logger = logging.getLogger(__name__)


# ── Abstract interface ────────────────────────────────────────────────────────

class BaseJobStore(ABC):
    @abstractmethod
    def create(self, job_id: str) -> JobState: ...

    @abstractmethod
    def get(self, job_id: str) -> Optional[JobState]: ...

    @abstractmethod
    def update(
        self,
        job_id: str,
        *,
        status: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        output_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> JobState: ...


# ── In-process store (single-worker deployments) ──────────────────────────────

class InMemoryJobStore(BaseJobStore):
    def __init__(self) -> None:
        self._store: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str) -> JobState:
        state = JobState(job_id=job_id)
        with self._lock:
            self._store[job_id] = state
        logger.debug("Job created: %s", job_id)
        return state

    def get(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._store.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        output_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> JobState:
        with self._lock:
            state = self._store[job_id]
            if status is not None:
                state.status = status
            if progress is not None:
                state.progress = max(0.0, min(1.0, progress))
            if message is not None:
                state.message = message
            if output_path is not None:
                state.output_path = output_path
            if error is not None:
                state.error = error
            state.updated_at = datetime.now(timezone.utc)
        return state


# ── Redis-backed store (multi-worker deployments) ─────────────────────────────

class RedisJobStore(BaseJobStore):
    _KEY_PREFIX = "handprint:job:"
    _TTL_SECONDS = 60 * 60 * 24  # 24 hours

    def __init__(self) -> None:
        import redis  # lazy import so redis is optional

        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        logger.info("RedisJobStore connected to %s", settings.redis_url)

    def _key(self, job_id: str) -> str:
        return f"{self._KEY_PREFIX}{job_id}"

    def create(self, job_id: str) -> JobState:
        state = JobState(job_id=job_id)
        self._redis.set(self._key(job_id), state.model_dump_json(), ex=self._TTL_SECONDS)
        logger.debug("Job created (redis): %s", job_id)
        return state

    def get(self, job_id: str) -> Optional[JobState]:
        raw = self._redis.get(self._key(job_id))
        if raw is None:
            return None
        return JobState(**json.loads(raw))

    def update(
        self,
        job_id: str,
        *,
        status: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        output_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> JobState:
        raw = self._redis.get(self._key(job_id))
        if raw is None:
            raise KeyError(f"Job {job_id!r} not found in Redis")
        state = JobState(**json.loads(raw))
        if status is not None:
            state.status = status
        if progress is not None:
            state.progress = max(0.0, min(1.0, progress))
        if message is not None:
            state.message = message
        if output_path is not None:
            state.output_path = output_path
        if error is not None:
            state.error = error
        state.updated_at = datetime.now(timezone.utc)
        self._redis.set(self._key(job_id), state.model_dump_json(), ex=self._TTL_SECONDS)
        return state


# ── Factory ───────────────────────────────────────────────────────────────────

def build_job_store() -> BaseJobStore:
    if settings.queue_backend == "redis":
        return RedisJobStore()
    return InMemoryJobStore()


# Module-level singleton
job_store: BaseJobStore = build_job_store()
