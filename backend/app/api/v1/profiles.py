"""Profiles router.

POST  /profiles                 — upload sample images, create profile
POST  /profiles/{id}/train      — kick off fine-tuning
GET   /profiles/{id}            — status + progress
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, FileTooLargeError, NotFoundError, ValidationError
from app.core.security import require_api_key
from app.db.models import Profile, ProfileStatus
from app.db.schemas import MessageResponse, ProfileCreate, ProfileResponse
from app.db.session import get_db
from app.workers.pool import submit_task
from app.workers.train_worker import run_training

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profiles", tags=["profiles"])


# ── POST /profiles ────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileResponse,
    summary="Create a new writer profile by uploading handwriting samples",
    dependencies=[Depends(require_api_key)],
)
async def create_profile(
    name: str = Form(..., description="Human-readable writer name"),
    images: list[UploadFile] = File(
        ..., description="15–30 handwriting sample images (JPEG/PNG)"
    ),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    # ── Validate count ────────────────────────────────────────────────────────
    if len(images) < settings.min_sample_images:
        raise ValidationError(
            f"At least {settings.min_sample_images} sample images are required "
            f"(got {len(images)})."
        )
    if len(images) > settings.max_sample_images:
        raise ValidationError(
            f"Maximum {settings.max_sample_images} sample images allowed "
            f"(got {len(images)})."
        )

    # ── Validate each image ───────────────────────────────────────────────────
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/tiff"}
    for img in images:
        if img.content_type not in allowed_types:
            raise ValidationError(
                f"Unsupported image type '{img.content_type}' for '{img.filename}'. "
                f"Allowed: JPEG, PNG, WEBP, TIFF."
            )
        # Size check — read in chunks to avoid buffering whole file in memory
        img.file.seek(0, 2)
        size = img.file.tell()
        img.file.seek(0)
        if size > settings.max_sample_image_bytes:
            raise FileTooLargeError(settings.max_sample_image_mb)

    # ── Persist images ────────────────────────────────────────────────────────
    profile_id = str(uuid.uuid4())
    sample_dir = settings.sample_dir / profile_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    for idx, img in enumerate(images):
        suffix = Path(img.filename or f"sample_{idx}.jpg").suffix or ".jpg"
        dest = sample_dir / f"{idx:03d}{suffix}"
        with dest.open("wb") as f:
            shutil.copyfileobj(img.file, f)

    # ── Create DB record ──────────────────────────────────────────────────────
    profile = Profile(
        id=profile_id,
        name=name,
        status=ProfileStatus.PENDING,
        sample_count=len(images),
        sample_dir=str(sample_dir),
    )
    db.add(profile)
    db.flush()

    logger.info("Profile %s created (%d samples).", profile_id, len(images))
    return ProfileResponse.model_validate(profile)


# ── POST /profiles/{id}/train ─────────────────────────────────────────────────

@router.post(
    "/{profile_id}/train",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MessageResponse,
    summary="Start fine-tuning for a profile",
    dependencies=[Depends(require_api_key)],
)
def start_training(
    profile_id: str,
    db: Session = Depends(get_db),
) -> MessageResponse:
    profile: Profile | None = db.get(Profile, profile_id)
    if profile is None:
        raise NotFoundError("Profile", profile_id)

    if profile.status in (ProfileStatus.TRAINING, ProfileStatus.READY):
        raise ConflictError(
            f"Profile is already in status '{profile.status}'. "
            "Only PENDING or FAILED profiles can be (re)trained."
        )

    # Reset for retry if previously FAILED
    profile.status = ProfileStatus.PENDING
    profile.train_progress = 0.0
    profile.error = None

    submit_task(run_training, profile_id)
    logger.info("Training enqueued for profile %s.", profile_id)
    return MessageResponse(message=f"Training started for profile '{profile_id}'.")


# ── GET /profiles/{id} ────────────────────────────────────────────────────────

@router.get(
    "/{profile_id}",
    response_model=ProfileResponse,
    summary="Get profile status and training progress",
    dependencies=[Depends(require_api_key)],
)
def get_profile(
    profile_id: str,
    db: Session = Depends(get_db),
) -> ProfileResponse:
    profile: Profile | None = db.get(Profile, profile_id)
    if profile is None:
        raise NotFoundError("Profile", profile_id)
    return ProfileResponse.model_validate(profile)
