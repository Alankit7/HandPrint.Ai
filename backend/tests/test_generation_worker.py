"""Tests for the generation worker function (model fully mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


def _make_line_tuples(n: int = 3) -> list[tuple[int, int, Image.Image]]:
    return [(0, i, Image.new("L", (400, 64), color=100)) for i in range(n)]


def test_run_generation_success(tmp_path: Path):
    """Happy path: valid PDF + samples → job marked DONE."""
    from reportlab.pdfgen import canvas as rl_canvas

    # Create a real PDF and sample images
    pdf_path = tmp_path / "in.pdf"
    c = rl_canvas.Canvas(str(pdf_path))
    c.drawString(72, 700, "Test line")
    c.save()

    sample_path = tmp_path / "sample.png"
    Image.new("L", (256, 64), color=200).save(sample_path)

    # Mock the model and pdf_to_line_images
    mock_model = MagicMock()
    mock_model.render_lines.return_value = [Image.new("L", (400, 64)) for _ in range(1)]

    with patch("app.workers.generation.get_model", return_value=mock_model), \
         patch("app.workers.generation.pdf_to_line_images", return_value=_make_line_tuples(2)), \
         patch("app.workers.generation.line_images_to_pdf") as mock_assemble, \
         patch("app.workers.generation.job_store") as mock_store:

        fake_out = tmp_path / "out.pdf"
        mock_assemble.return_value = fake_out

        from app.workers.generation import run_generation
        run_generation("test-job", str(pdf_path), [str(sample_path)])

        # Model was style-conditioned
        mock_model.set_style.assert_called_once()
        # Lines were rendered
        mock_model.render_lines.assert_called_once()
        # Job was marked done
        calls = [str(c) for c in mock_store.update.call_args_list]
        done_calls = [c for c in calls if "done" in c.lower()]
        assert done_calls, "Job was never marked DONE"


def test_run_generation_missing_pdf(tmp_path: Path):
    """Missing PDF file → job marked FAILED, no exception propagated."""
    sample_path = tmp_path / "sample.png"
    Image.new("L", (256, 64)).save(sample_path)

    with patch("app.workers.generation.get_model", return_value=MagicMock()), \
         patch("app.workers.generation.job_store") as mock_store:

        from app.workers.generation import run_generation
        run_generation("test-job-2", str(tmp_path / "missing.pdf"), [str(sample_path)])

        calls_str = str(mock_store.update.call_args_list)
        assert "failed" in calls_str.lower()


def test_run_generation_no_samples(tmp_path: Path):
    """No sample images → job marked FAILED."""
    pdf_path = tmp_path / "in.pdf"
    from reportlab.pdfgen import canvas as rl_canvas
    c = rl_canvas.Canvas(str(pdf_path))
    c.drawString(72, 700, "hi")
    c.save()

    with patch("app.workers.generation.get_model", return_value=MagicMock()), \
         patch("app.workers.generation.job_store") as mock_store:

        from app.workers.generation import run_generation
        run_generation("test-job-3", str(pdf_path), [])

        calls_str = str(mock_store.update.call_args_list)
        assert "failed" in calls_str.lower()
