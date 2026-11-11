"""Tests for POST /profiles and GET /profiles/{id}."""

from __future__ import annotations

import pytest

from tests.conftest import HEADERS, make_png_bytes, upload_files_for_profile


# ── POST /profiles ────────────────────────────────────────────────────────────

def test_create_profile_success(client):
    files = upload_files_for_profile(n=2)
    r = client.post("/profiles", data={"name": "Alice"}, files=files, headers=HEADERS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Alice"
    assert body["status"] == "pending"
    assert body["sample_count"] == 2
    assert "id" in body


def test_create_profile_too_few_images(client):
    # MIN_SAMPLE_IMAGES is set to 1 in conftest, so 0 images should fail
    r = client.post("/profiles", data={"name": "Bob"}, files=[], headers=HEADERS)
    assert r.status_code == 422


def test_create_profile_too_many_images(client):
    files = upload_files_for_profile(n=31)  # MAX is 30
    r = client.post("/profiles", data={"name": "Carol"}, files=files, headers=HEADERS)
    assert r.status_code == 422


def test_create_profile_wrong_image_type(client):
    files = [("images", ("bad.pdf", b"%PDF-fake", "application/pdf"))]
    r = client.post("/profiles", data={"name": "Dave"}, files=files, headers=HEADERS)
    assert r.status_code == 422


def test_create_profile_image_too_large(client, monkeypatch):
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "max_sample_image_mb", 0)
    monkeypatch.setattr(cfg_module.settings, "max_sample_image_bytes", 1)
    files = upload_files_for_profile(n=1)
    r = client.post("/profiles", data={"name": "Eve"}, files=files, headers=HEADERS)
    assert r.status_code == 413


def test_create_profile_missing_name(client):
    files = upload_files_for_profile(n=2)
    r = client.post("/profiles", files=files, headers=HEADERS)
    assert r.status_code == 422


# ── GET /profiles/{id} ────────────────────────────────────────────────────────

def test_get_profile_success(client):
    files = upload_files_for_profile(n=1)
    create_r = client.post("/profiles", data={"name": "Frank"}, files=files, headers=HEADERS)
    pid = create_r.json()["id"]

    r = client.get(f"/profiles/{pid}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_get_profile_not_found(client):
    r = client.get("/profiles/does-not-exist", headers=HEADERS)
    assert r.status_code == 404


def test_profile_response_has_required_fields(client):
    files = upload_files_for_profile(n=1)
    r = client.post("/profiles", data={"name": "Grace"}, files=files, headers=HEADERS)
    body = r.json()
    for field in ("id", "name", "status", "sample_count", "train_progress", "created_at", "updated_at"):
        assert field in body, f"Missing field: {field}"
