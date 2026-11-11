"""Pydantic v2 request/response schemas (separate from ORM models)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.models import JobStatus, ProfileStatus


# ── Profile schemas ───────────────────────────────────────────────────────────

class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable writer name")


class ProfileResponse(BaseModel):
    id: str
    name: str
    status: ProfileStatus
    sample_count: int
    train_progress: float
    error: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Job schemas ───────────────────────────────────────────────────────────────

class ConvertRequest(BaseModel):
    profile_id: str = Field(..., description="ID of a READY profile")


class JobResponse(BaseModel):
    id: str
    profile_id: str
    status: JobStatus
    progress: float
    message: str
    error: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Generic ───────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
