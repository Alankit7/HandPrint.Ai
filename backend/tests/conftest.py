"""Shared pytest fixtures.

Uses an in-memory SQLite database and overrides all file-system paths to
temp directories so tests are fully isolated and leave no residue.
"""

from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Inject env before anything imports Settings ───────────────────────────────
_tmpdir = tempfile.mkdtemp()
os.environ["API_KEY"] = "test-secret-api-key"
os.environ["DATABASE_URL"] = "sqlite://"          # in-memory
os.environ["UPLOAD_DIR"] = f"{_tmpdir}/uploads"
os.environ["SAMPLE_DIR"] = f"{_tmpdir}/samples"
os.environ["OUTPUT_DIR"] = f"{_tmpdir}/outputs"
os.environ["MIN_SAMPLE_IMAGES"] = "1"             # relax for tests
os.environ["MAX_SAMPLE_IMAGES"] = "30"
os.environ["WORKER_THREADS"] = "1"
os.environ["CLEANUP_AGE_HOURS"] = "24"

from app.db.base import Base
from app.db.models import Job, JobStatus, Profile, ProfileStatus
from app.db.session import get_db
from app.main import create_app

VALID_KEY = "test-secret-api-key"
HEADERS = {"X-API-Key": VALID_KEY}


# ── Database override ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    # Clean tables between tests
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


@pytest.fixture()
def client(db_session):
    """HTTP test client with DB and worker pool overridden."""
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── File helpers ──────────────────────────────────────────────────────────────

def make_png_bytes(width: int = 200, height: int = 64) -> bytes:
    """Return bytes of a tiny greyscale PNG."""
    buf = BytesIO()
    Image.new("L", (width, height), color=180).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def make_pdf_bytes() -> bytes:
    """Return bytes of a minimal valid PDF."""
    from reportlab.pdfgen import canvas as rl_canvas
    buf = BytesIO()
    c = rl_canvas.Canvas(buf)
    c.drawString(72, 700, "Test line")
    c.save()
    buf.seek(0)
    return buf.read()


def upload_files_for_profile(n: int = 2) -> list[tuple[str, tuple]]:
    """Build a multipart `images` file list for profile creation."""
    return [
        ("images", (f"sample_{i}.png", make_png_bytes(), "image/png"))
        for i in range(n)
    ]


@pytest.fixture()
def ready_profile(db_session, tmp_path) -> Profile:
    """A Profile already in READY status with a fake checkpoint."""
    ckpt_dir = tmp_path / "ckpt"
    ckpt_dir.mkdir()
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    p = Profile(
        id="profile-ready",
        name="Test Writer",
        status=ProfileStatus.READY,
        sample_count=2,
        sample_dir=str(sample_dir),
        checkpoint_path=str(ckpt_dir),
        train_progress=1.0,
    )
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture()
def done_job(db_session, ready_profile, tmp_path) -> Job:
    """A Job in DONE status with a real (fake) output PDF on disk."""
    out = tmp_path / "out.pdf"
    out.write_bytes(make_pdf_bytes())
    j = Job(
        id="job-done",
        profile_id=ready_profile.id,
        input_pdf_path=str(tmp_path / "in.pdf"),
        output_pdf_path=str(out),
        status=JobStatus.DONE,
        progress=1.0,
        message="Done",
    )
    db_session.add(j)
    db_session.commit()
    return j
