"""Tests for API-key authentication on every protected endpoint."""

from __future__ import annotations

import pytest

from tests.conftest import HEADERS, make_png_bytes, upload_files_for_profile


PROTECTED_ROUTES = [
    ("POST", "/profiles", None),
    ("POST", "/profiles/fake-id/train", None),
    ("GET",  "/profiles/fake-id", None),
    ("POST", "/convert", None),
    ("GET",  "/jobs/fake-id", None),
    ("GET",  "/download/fake-id", None),
]


@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
def test_missing_key_returns_401(client, method, path, body):
    resp = getattr(client, method.lower())(path)
    assert resp.status_code == 401, f"{method} {path}: expected 401, got {resp.status_code}"


@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
def test_wrong_key_returns_403(client, method, path, body):
    resp = getattr(client, method.lower())(path, headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 403, f"{method} {path}: expected 403, got {resp.status_code}"


def test_health_requires_no_key(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_valid_key_passes_auth(client):
    """A valid key on a non-existent resource should return 404, not 401/403."""
    r = client.get("/profiles/nonexistent", headers=HEADERS)
    assert r.status_code == 404
