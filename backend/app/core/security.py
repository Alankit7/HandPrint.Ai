"""API-key authentication dependency.

Clients must pass the key in the ``X-API-Key`` request header.
The key is compared with ``settings.api_key`` using a constant-time
comparison to guard against timing attacks.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_API_KEY_HEADER)) -> str:
    """FastAPI dependency — raises 401 when the key is missing or wrong."""
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    # hmac.compare_digest prevents timing-based enumeration
    if not hmac.compare_digest(key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
    return key
