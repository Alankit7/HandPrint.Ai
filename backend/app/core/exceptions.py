"""Domain exceptions and their FastAPI exception handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class NotFoundError(Exception):
    def __init__(self, resource: str, id: str) -> None:
        self.resource = resource
        self.id = id
        super().__init__(f"{resource} '{id}' not found.")


class ConflictError(Exception):
    """Raised when an operation is not valid given the current state."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class FileTooLargeError(Exception):
    def __init__(self, limit_mb: int) -> None:
        super().__init__(f"File exceeds the {limit_mb} MB limit.")
        self.limit_mb = limit_mb


class ValidationError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(FileTooLargeError)
    async def _too_large(_: Request, exc: FileTooLargeError) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def _validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
