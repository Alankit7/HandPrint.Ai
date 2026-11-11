"""Pydantic schemas for job state, used by both API and in-process store."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class JobCreate(BaseModel):
    """Internal DTO created when a job is enqueued."""

    job_id: str
    pdf_path: str          # absolute path to the uploaded PDF
    sample_paths: list[str]  # absolute paths to reference handwriting images
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobState(BaseModel):
    """Full job state stored in the job store."""

    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress: float = Field(0.0, ge=0.0, le=1.0)   # 0–1
    message: str = ""
    output_path: Optional[str] = None               # set when DONE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None


class JobStatusResponse(BaseModel):
    """Public API response schema."""

    job_id: str
    status: JobStatus
    progress: float
    message: str
    download_token: Optional[str] = None   # only present when status == DONE


class JobCreateResponse(BaseModel):
    """Returned immediately after the client submits a job."""

    job_id: str
    status: JobStatus
    message: str = "Job accepted"
