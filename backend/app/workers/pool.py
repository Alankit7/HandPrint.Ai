"""Module-level thread-pool executor shared by all background tasks.

Import ``submit_task`` everywhere you need to dispatch work off the
request thread.  The pool is sized by ``settings.worker_threads``.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

_executor: concurrent.futures.ThreadPoolExecutor | None = None


def get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.worker_threads,
            thread_name_prefix="hw-worker",
        )
        logger.info("Worker pool started (%d threads).", settings.worker_threads)
    return _executor


def submit_task(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Fire-and-forget: submit *fn* to the thread pool, log any exception."""
    future = get_executor().submit(fn, *args, **kwargs)

    def _on_done(f: concurrent.futures.Future) -> None:
        exc = f.exception()
        if exc:
            logger.error("Background task %s raised: %s", fn.__name__, exc, exc_info=exc)

    future.add_done_callback(_on_done)


def shutdown_pool(wait: bool = True) -> None:
    """Call at application shutdown."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None
        logger.info("Worker pool shut down.")
