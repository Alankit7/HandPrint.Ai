"""Tests for token signing and verification."""

from __future__ import annotations

import pytest

from app.core.security import generate_job_id, make_job_token, verify_job_token


def test_round_trip():
    job_id = generate_job_id()
    token = make_job_token(job_id)
    assert verify_job_token(token) == job_id


def test_tampered_signature():
    job_id = generate_job_id()
    token = make_job_token(job_id)
    bad_token = token[:-4] + "XXXX"
    assert verify_job_token(bad_token) is None


def test_tampered_job_id():
    token = make_job_token("real-job-id")
    # Replace job_id part
    _, sig = token.rsplit(".", 1)
    assert verify_job_token(f"fake-job-id.{sig}") is None


def test_malformed_token():
    assert verify_job_token("no-dot-here") is None
    assert verify_job_token("") is None


def test_unique_job_ids():
    ids = {generate_job_id() for _ in range(100)}
    assert len(ids) == 100
