"""Tests confirming that the ML stubs raise NotImplementedError as documented."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ml.stubs import render_pdf, train_profile


def test_train_profile_raises_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError):
        train_profile(
            profile_id="x",
            sample_dir=tmp_path,
            checkpoint_out_dir=tmp_path,
            progress_cb=lambda p: None,
        )


def test_render_pdf_raises_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError):
        render_pdf(
            input_pdf_path=tmp_path / "in.pdf",
            checkpoint_path=tmp_path / "ckpt",
            output_pdf_path=tmp_path / "out.pdf",
            progress_cb=lambda p: None,
        )


def test_progress_callback_signature_accepted(tmp_path):
    """Verify the stub accepts any callable as progress_cb (type contract)."""
    received: list[float] = []
    with pytest.raises(NotImplementedError):
        train_profile(
            profile_id="y",
            sample_dir=tmp_path,
            checkpoint_out_dir=tmp_path,
            progress_cb=lambda p: received.append(p),
        )
    # Stub raises before calling the callback, that's fine
    assert received == []
