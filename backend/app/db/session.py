"""SQLAlchemy engine + session factory.

For SQLite the check_same_thread flag must be False because FastAPI can
hand a request to a different thread from the one that opened the session.
We use NullPool so each thread gets its own connection — safe for SQLite.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base

logger = logging.getLogger(__name__)

# Build the engine — SQLite needs two special kwargs
_connect_args = {}
_pool_kwargs: dict = {}

if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    # StaticPool keeps one in-process connection; fine for single-process dev.
    # For multi-worker production swap to NullPool.
    _pool_kwargs = {"poolclass": StaticPool}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=False,          # set True to log every SQL statement
    **_pool_kwargs,
)

# Enable WAL mode for better concurrent reads on SQLite
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    if settings.database_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables (idempotent — safe to call at every startup)."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified / created.")


@contextmanager
def get_db_ctx() -> Generator[Session, None, None]:
    """Context-manager style session — use in background workers."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a session, commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
