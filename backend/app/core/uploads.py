"""Shared helpers for validating and saving uploaded files.

Centralises the ``file.seek(0, 2) / tell / seek(0)`` pattern so routers
stay concise and the logic is tested in one place.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile

from app.core.exceptions import FileTooLargeError, ValidationError


def get_upload_size(upload: UploadFile) -> int:
    """Return the byte size of *upload* and reset the file cursor to 0.

    Uses seek/tell because UploadFile does not expose a ``size`` attribute
    reliably for all ASGI servers.
    """
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def validate_pdf(upload: UploadFile, max_bytes: int, max_mb: int) -> None:
    """Raise :class:`~app.core.exceptions.ValidationError` or
    :class:`~app.core.exceptions.FileTooLargeError` if *upload* is not a
    valid PDF within the size limit.
    """
    if upload.content_type not in ("application/pdf", "application/octet-stream"):
        raise ValidationError(
            f"Only PDF files are accepted (got '{upload.content_type}')."
        )
    if get_upload_size(upload) > max_bytes:
        raise FileTooLargeError(max_mb)


def validate_image(upload: UploadFile, max_bytes: int, max_mb: int) -> None:
    """Raise if *upload* is not a supported image type or exceeds the size limit."""
    allowed = {"image/jpeg", "image/png", "image/webp", "image/tiff"}
    if upload.content_type not in allowed:
        raise ValidationError(
            f"Unsupported image type '{upload.content_type}' for '{upload.filename}'. "
            f"Allowed: JPEG, PNG, WEBP, TIFF."
        )
    if get_upload_size(upload) > max_bytes:
        raise FileTooLargeError(max_mb)


def save_upload(upload: UploadFile, dest: Path) -> Path:
    """Stream *upload* to *dest* (must have an open parent dir) and return *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest
