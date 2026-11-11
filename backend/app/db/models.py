"""ORM models: Profile and Job.

Profile  — a named writer whose handwriting style has been (or is being) trained.
Job      — a single PDF-conversion request tied to a Profile.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────────────────

class ProfileStatus(str, PyEnum):
    PENDING = "pending"       # created, no training started
    TRAINING = "training"     # fine-tuning in progress
    READY = "ready"           # trained, can accept convert jobs
    FAILED = "failed"         # training failed


class JobStatus(str, PyEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# ── Profile ───────────────────────────────────────────────────────────────────

class Profile(Base):
    """Represents one person's handwriting style."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ProfileStatus.PENDING)
    # Number of sample images stored
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Path to the directory holding the sample images for this profile
    sample_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Path to the trained model checkpoint (populated after training)
    checkpoint_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Training progress 0.0 – 1.0
    train_progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    jobs: Mapped[list[Job]] = relationship("Job", back_populates="profile", cascade="all, delete-orphan")


# ── Job ───────────────────────────────────────────────────────────────────────

class Job(Base):
    """A single PDF conversion request."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    # Absolute path to the uploaded source PDF
    input_pdf_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Absolute path to the generated output PDF (set when DONE)
    output_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.QUEUED)
    # Render progress 0.0 – 1.0
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="Queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="jobs")
