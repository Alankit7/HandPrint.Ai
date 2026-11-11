"""Job queue abstraction.

Supports two backends:
  - ``simple``: runs the worker function in a background thread (single-process).
  - ``redis``: delegates to RQ (Redis Queue) for multi-worker deployments.
"""

from __future__ import annotations

import concurrent.futures
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level thread pool used by SimpleQueue
_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.backend_workers,
            thread_name_prefix="hw-worker",
        )
    return _executor


# ── Abstract interface ────────────────────────────────────────────────────────

class BaseQueue(ABC):
    @abstractmethod
    def enqueue(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Submit *func(*args, **kwargs)* for async execution."""


# ── In-process thread queue ───────────────────────────────────────────────────

class SimpleQueue(BaseQueue):
    def enqueue(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        future = _get_executor().submit(func, *args, **kwargs)

        def _on_done(f: concurrent.futures.Future[Any]) -> None:
            exc = f.exception()
            if exc:
                logger.error(
                    "Background task %s raised: %s", func.__name__, exc, exc_info=exc
                )

        future.add_done_callback(_on_done)
        logger.debug("Enqueued task %s (simple queue)", func.__name__)


# ── RQ (Redis Queue) ──────────────────────────────────────────────────────────

class RQQueue(BaseQueue):
    def __init__(self) -> None:
        from redis import Redis
        from rq import Queue

        self._redis = Redis.from_url(settings.redis_url)
        self._q = Queue(connection=self._redis)
        logger.info("RQQueue connected to %s", settings.redis_url)

    def enqueue(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._q.enqueue(func, *args, **kwargs)
        logger.debug("Enqueued task %s (rq)", func.__name__)


# ── Factory ───────────────────────────────────────────────────────────────────

def build_queue() -> BaseQueue:
    if settings.queue_backend == "redis":
        return RQQueue()
    return SimpleQueue()


# Module-level singleton
job_queue: BaseQueue = build_queue()
