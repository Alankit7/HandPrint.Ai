"""FastAPI application factory.

Startup
-------
1. Configure logging.
2. Create / migrate DB tables (idempotent).
3. Start APScheduler for the cleanup task.

Shutdown
--------
1. Stop the scheduler.
2. Drain the worker thread pool.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health as health_router
from app.api.v1.jobs import convert_router, download_router, jobs_router
from app.api.v1.profiles import router as profiles_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import init_db
from app.workers.cleanup import run_cleanup
from app.workers.pool import shutdown_pool

_scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ───────────────────────────────────────────────────────────────
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    init_db()

    _scheduler.add_job(
        run_cleanup,
        "interval",
        minutes=settings.cleanup_interval_minutes,
        id="cleanup",
        replace_existing=True,
    )
    _scheduler.start()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    _scheduler.shutdown(wait=False)
    shutdown_pool(wait=True)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Handprint AI — Job Queue API",
        description=(
            "Upload handwriting samples, train a writer profile, "
            "then convert any printed PDF into that person's handwriting."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health_router.router)
    app.include_router(profiles_router)
    app.include_router(convert_router)
    app.include_router(jobs_router)
    app.include_router(download_router)

    return app


app = create_app()
