"""Integration tests for the FastAPI endpoints.

The handwriting model and worker are mocked — these tests verify HTTP
contract, validation, and status-polling flow without needing a GPU.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen import canvas as rl_canvas


def _make_pdf_bytes() -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf)
    c.drawString(72, 700, "Integration test line")
    c.save()
    buf.seek(0)
    return buf.read()


def _make_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (256, 64), color=180).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "model" in body


# ── POST /v1/jobs ─────────────────────────────────────────────────────────────

def test_create_job_success(client: TestClient):
    r = client.post(
        "/v1/jobs",
        files={
            "pdf": ("input.pdf", _make_pdf_bytes(), "application/pdf"),
            "samples": ("s1.png", _make_png_bytes(), "image/png"),
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "pending"


def test_create_job_missing_pdf(client: TestClient):
    r = client.post(
        "/v1/jobs",
        files={
            "samples": ("s1.png", _make_png_bytes(), "image/png"),
        },
    )
    assert r.status_code == 422


def test_create_job_missing_sample(client: TestClient):
    r = client.post(
        "/v1/jobs",
        files={
            "pdf": ("input.pdf", _make_pdf_bytes(), "application/pdf"),
        },
    )
    assert r.status_code == 422


def test_create_job_wrong_content_type(client: TestClient):
    """Sending a PNG as the PDF should be rejected."""
    r = client.post(
        "/v1/jobs",
        files={
            "pdf": ("input.png", _make_png_bytes(), "image/png"),
            "samples": ("s1.png", _make_png_bytes(), "image/png"),
        },
    )
    assert r.status_code == 415


# ── GET /v1/jobs/{job_id} ─────────────────────────────────────────────────────

def test_poll_pending(client: TestClient):
    r = client.post(
        "/v1/jobs",
        files={
            "pdf": ("input.pdf", _make_pdf_bytes(), "application/pdf"),
            "samples": ("s1.png", _make_png_bytes(), "image/png"),
        },
    )
    job_id = r.json()["job_id"]
    r2 = client.get(f"/v1/jobs/{job_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["job_id"] == job_id
    assert body["status"] in ("pending", "processing", "done")


def test_poll_nonexistent(client: TestClient):
    r = client.get("/v1/jobs/nonexistent-id")
    assert r.status_code == 404


# ── GET /v1/jobs/{job_id}/download ───────────────────────────────────────────

def test_download_requires_token(client: TestClient):
    r = client.post(
        "/v1/jobs",
        files={
            "pdf": ("input.pdf", _make_pdf_bytes(), "application/pdf"),
            "samples": ("s1.png", _make_png_bytes(), "image/png"),
        },
    )
    job_id = r.json()["job_id"]
    # No token → 422
    r2 = client.get(f"/v1/jobs/{job_id}/download")
    assert r2.status_code == 422


def test_download_bad_token(client: TestClient):
    r = client.post(
        "/v1/jobs",
        files={
            "pdf": ("input.pdf", _make_pdf_bytes(), "application/pdf"),
            "samples": ("s1.png", _make_png_bytes(), "image/png"),
        },
    )
    job_id = r.json()["job_id"]
    r2 = client.get(f"/v1/jobs/{job_id}/download", params={"token": "bad.token"})
    assert r2.status_code == 403


def test_full_job_flow(client: TestClient, tmp_path: Path):
    """Submit job → poll until done → download (mocked generation)."""
    from app.core.security import make_job_token
    from app.models.job import JobStatus
    from app.services.job_store import job_store

    r = client.post(
        "/v1/jobs",
        files={
            "pdf": ("input.pdf", _make_pdf_bytes(), "application/pdf"),
            "samples": ("s1.png", _make_png_bytes(), "image/png"),
        },
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # Manually mark the job as done (since the worker is mocked/threaded)
    fake_pdf = tmp_path / "fake_output.pdf"
    fake_pdf.write_bytes(_make_pdf_bytes())
    job_store.update(
        job_id,
        status=JobStatus.DONE,
        progress=1.0,
        message="Done",
        output_path=str(fake_pdf),
    )

    # Poll
    r2 = client.get(f"/v1/jobs/{job_id}")
    assert r2.json()["status"] == "done"
    assert r2.json()["download_token"] is not None
    token = r2.json()["download_token"]

    # Download
    r3 = client.get(f"/v1/jobs/{job_id}/download", params={"token": token})
    assert r3.status_code == 200
    assert r3.headers["content-type"] == "application/pdf"
