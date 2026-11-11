"""Jobs router.

POST  /convert       — upload PDF + profile_id → queued job
GET   /jobs/{id}     — job status + progress
GET   /download/{id} — stream finished PDF
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import require_api_key
from app.core.uploads import save_upload, validate_pdf
from app.db.models import Job, JobStatus, Profile, ProfileStatus
from app.db.schemas import JobResponse, MessageResponse
from app.db.session import get_db
from app.workers.convert_worker import run_conversion
from app.workers.pool import submit_task

logger = logging.getLogger(__name__)

convert_router = APIRouter(tags=["convert"])
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])
download_router = APIRouter(prefix="/download", tags=["download"])


# ── POST /convert ─────────────────────────────────────────────────────────────

@convert_router.post(
    "/convert",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
    summary="Submit a PDF conversion job",
    dependencies=[Depends(require_api_key)],
)
async def create_convert_job(
    profile_id: str = Form(..., description="ID of a READY profile"),
    pdf: UploadFile = File(..., description="Printed PDF to convert"),
    db: Session = Depends(get_db),
) -> JobResponse:
    # ── Validate PDF type + size ──────────────────────────────────────────────
    validate_pdf(pdf, settings.max_pdf_bytes, settings.max_pdf_mb)

    # ── Validate profile ──────────────────────────────────────────────────────
    profile: Profile | None = db.get(Profile, profile_id)
    if profile is None:
        raise NotFoundError("Profile", profile_id)
    if profile.status != ProfileStatus.READY:
        raise ConflictError(
            f"Profile '{profile_id}' is not READY (current status: '{profile.status}'). "
            "Train the profile first."
        )

    # ── Save PDF ──────────────────────────────────────────────────────────────
    job_id = str(uuid.uuid4())
    pdf_dest = save_upload(pdf, settings.upload_dir / job_id / (pdf.filename or "input.pdf"))

    # ── Create job record ─────────────────────────────────────────────────────
    job = Job(
        id=job_id,
        profile_id=profile_id,
        input_pdf_path=str(pdf_dest),
        status=JobStatus.QUEUED,
        message="Queued",
    )
    db.add(job)
    db.flush()

    submit_task(run_conversion, job_id)
    logger.info("Conversion job %s queued (profile=%s).", job_id, profile_id)
    return JobResponse.model_validate(job)


# ── GET /jobs/{id} ────────────────────────────────────────────────────────────

@jobs_router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get job status and render progress",
    dependencies=[Depends(require_api_key)],
)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobResponse:
    job: Job | None = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)
    return JobResponse.model_validate(job)


# ── GET /download/{id} ────────────────────────────────────────────────────────

@download_router.get(
    "/{job_id}",
    summary="Download the finished handwritten PDF",
    response_description="The rendered PDF file",
    dependencies=[Depends(require_api_key)],
)
def download_result(
    job_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    job: Job | None = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)
    if job.status != JobStatus.DONE:
        raise ConflictError(
            f"Job '{job_id}' is not DONE yet (status: '{job.status}'). "
            "Poll GET /jobs/{id} until status is 'done'."
        )
    if not job.output_pdf_path:
        raise ConflictError("Output file path is missing — this is a server-side bug.")

    output = Path(job.output_pdf_path)
    if not output.exists():
        raise ConflictError(
            "Output file has been removed (likely by the cleanup task). "
            "Re-submit the conversion job."
        )

    return FileResponse(
        path=str(output),
        media_type="application/pdf",
        filename=f"handprint_{job_id}.pdf",
    )
