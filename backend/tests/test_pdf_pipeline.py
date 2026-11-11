"""Tests for PDF ↔ image pipeline (uses reportlab to create test PDFs)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


def _make_pdf(path: Path, text: str = "Line one\nLine two\nLine three") -> Path:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    y = 700
    for line in text.splitlines():
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return path


def test_pdf_to_line_images_returns_list(tmp_path: Path):
    from app.services.pdf_pipeline import pdf_to_line_images

    pdf = _make_pdf(tmp_path / "test.pdf")
    lines = pdf_to_line_images(pdf, img_height_px=64)
    assert isinstance(lines, list)
    # Should extract at least one line
    assert len(lines) >= 1


def test_pdf_to_line_images_height(tmp_path: Path):
    from app.services.pdf_pipeline import pdf_to_line_images

    pdf = _make_pdf(tmp_path / "test.pdf")
    for _page, _line, img in pdf_to_line_images(pdf, img_height_px=64):
        assert img.height == 64


def test_pdf_to_line_images_pil_images(tmp_path: Path):
    from app.services.pdf_pipeline import pdf_to_line_images

    pdf = _make_pdf(tmp_path / "test.pdf")
    for _page, _line, img in pdf_to_line_images(pdf, img_height_px=32):
        assert isinstance(img, Image.Image)


def test_line_images_to_pdf_creates_file(tmp_path: Path):
    from app.services.pdf_pipeline import line_images_to_pdf

    imgs = [Image.new("L", (400, 64), color=100) for _ in range(5)]
    out = tmp_path / "output.pdf"
    result = line_images_to_pdf(imgs, out)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_line_images_to_pdf_multi_page(tmp_path: Path):
    """Force a page break by using many tall images."""
    from app.services.pdf_pipeline import line_images_to_pdf

    # 100 images of 100px height each should overflow a single A4 page
    imgs = [Image.new("L", (500, 100), color=50) for _ in range(100)]
    out = tmp_path / "multipage.pdf"
    line_images_to_pdf(imgs, out)
    assert out.exists()


def test_pipeline_round_trip(tmp_path: Path):
    """Create a PDF, extract lines, assemble a new PDF — no errors end-to-end."""
    from app.services.pdf_pipeline import line_images_to_pdf, pdf_to_line_images

    pdf = _make_pdf(tmp_path / "in.pdf", "Hello World\nSecond line here")
    lines = [img for _, _, img in pdf_to_line_images(pdf, img_height_px=64)]
    assert lines
    out = tmp_path / "out.pdf"
    line_images_to_pdf(lines, out)
    assert out.exists()
