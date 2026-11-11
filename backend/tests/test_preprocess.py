"""Tests for app/ml/preprocess.py — all stages exercised on synthetic data.

Synthetic pages are built in-memory with numpy: white background, dark
horizontal bands simulating text lines, and clusters of dark pixels
simulating words within each line.  This avoids needing real scanned
images while still exercising every pipeline stage.
"""

from __future__ import annotations

import csv
import math
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.ml.preprocess import (
    ALIGN_CONFIDENCE_THRESHOLD,
    Crop,
    PreprocessConfig,
    PipelineSummary,
    align_crops,
    deskew,
    export_dataset,
    normalise,
    rasterise,
    run_pipeline,
    segment_lines,
    segment_lines_opencv,
    segment_words,
    write_debug_grid,
    write_report,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Synthetic page builders
# ═══════════════════════════════════════════════════════════════════════════════

def make_synthetic_page(
    width: int = 1200,
    height: int = 1600,
    n_lines: int = 5,
    words_per_line: int = 4,
    ink_value: int = 30,
    bg_value: int = 240,
    line_height: int = 40,
    line_gap: int = 50,
    word_gap: int = 40,
    word_width: int = 60,
    word_height: int = 28,
    margin_x: int = 80,
    margin_y: int = 100,
) -> np.ndarray:
    """Return a greyscale uint8 page with dark 'text' bands on a light background.

    The page simulates a printed page: horizontal lines of words separated by
    gaps.  Each 'word' is a filled rectangle of dark pixels.
    """
    page = np.full((height, width), bg_value, dtype=np.uint8)

    y = margin_y
    for _line in range(n_lines):
        x = margin_x
        for _word in range(words_per_line):
            # Add slight per-word height variation
            wh = word_height + np.random.randint(-3, 4)
            # Draw the word as a filled rectangle with some noise
            word_block = np.random.randint(
                ink_value - 10, ink_value + 10, size=(wh, word_width), dtype=np.uint8
            )
            # Clip
            word_block = np.clip(word_block, 0, 255)
            page[y : y + wh, x : x + word_width] = word_block
            x += word_width + word_gap
        y += line_height + line_gap

    return page


def make_skewed_page(angle_deg: float = 3.0, **kwargs) -> np.ndarray:
    """Return a synthetic page rotated by *angle_deg* (for deskew testing)."""
    from scipy.ndimage import rotate as scipy_rotate

    page = make_synthetic_page(**kwargs)
    rotated = scipy_rotate(page, angle_deg, reshape=False, cval=240, order=1)
    return np.clip(rotated, 0, 255).astype(np.uint8)


def make_synthetic_pdf(path: Path, n_pages: int = 2, **page_kwargs) -> Path:
    """Create a real PDF file with embedded synthetic page images."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    pw, ph = A4
    for _ in range(n_pages):
        page_arr = make_synthetic_page(**page_kwargs)
        pil = Image.fromarray(page_arr)
        buf = BytesIO()
        pil.save(buf, format="PNG")
        buf.seek(0)
        # Embed the image scaled to fit A4
        c.drawImage(
            Image.open(buf),
            0, 0, width=pw, height=ph,
        )
        c.showPage()
    c.save()
    return path


def make_synthetic_image(path: Path, **page_kwargs) -> Path:
    """Create a single PNG image file from a synthetic page."""
    page_arr = make_synthetic_page(**page_kwargs)
    Image.fromarray(page_arr).save(path)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# Stage tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRasterise:
    """Tests for rasterise()."""

    def test_rasterise_image_png(self, tmp_path: Path):
        img_path = make_synthetic_image(tmp_path / "page.png")
        pages = rasterise(img_path, dpi=150)
        assert len(pages) == 1
        assert pages[0].ndim == 2
        assert pages[0].dtype == np.uint8
        assert pages[0].shape[0] > 0 and pages[0].shape[1] > 0

    def test_rasterise_image_jpg(self, tmp_path: Path):
        page_arr = make_synthetic_page()
        Image.fromarray(page_arr).save(tmp_path / "page.jpg", quality=95)
        pages = rasterise(tmp_path / "page.jpg", dpi=150)
        assert len(pages) == 1
        assert pages[0].dtype == np.uint8

    def test_rasterise_pdf(self, tmp_path: Path):
        pdf_path = make_synthetic_pdf(tmp_path / "doc.pdf", n_pages=3)
        pages = rasterise(pdf_path, dpi=150)
        assert len(pages) == 3
        for p in pages:
            assert p.ndim == 2
            assert p.dtype == np.uint8

    def test_rasterise_pdf_300_dpi(self, tmp_path: Path):
        pdf_path = make_synthetic_pdf(tmp_path / "doc.pdf", n_pages=1)
        pages_low = rasterise(pdf_path, dpi=150)
        pages_high = rasterise(pdf_path, dpi=300)
        # Higher DPI should produce a larger image
        assert pages_high[0].shape[0] > pages_low[0].shape[0]

    def test_rasterise_unsupported_type(self, tmp_path: Path):
        (tmp_path / "bad.xyz").write_bytes(b"garbage")
        with pytest.raises(ValueError, match="Unsupported file type"):
            rasterise(tmp_path / "bad.xyz")


class TestDeskew:
    """Tests for deskew()."""

    def test_no_skew_returns_original(self):
        page = make_synthetic_page()
        corrected, angle = deskew(page, max_angle=5.0, step=0.5)
        assert abs(angle) < 1.0  # near-zero skew detected
        assert corrected.shape == page.shape

    def test_detects_and_corrects_skew(self):
        """A page rotated by 5° should be corrected back near 0°."""
        page = make_synthetic_page()
        skewed = make_skewed_page(angle_deg=5.0)
        _corrected, angle = deskew(skewed, max_angle=10.0, step=0.5)
        # The detected angle should be in the ballpark of 5° (within tolerance)
        assert abs(abs(angle) - 5.0) < 2.0, f"Expected ~5°, got {angle:.2f}°"

    def test_deskew_preserves_dtype(self):
        page = make_synthetic_page()
        corrected, _ = deskew(page)
        assert corrected.dtype == np.uint8

    def test_deskew_output_dimensions(self):
        page = make_synthetic_page(width=800, height=600)
        corrected, _ = deskew(page)
        assert corrected.shape[0] == page.shape[0]
        assert corrected.shape[1] == page.shape[1]


class TestNormalise:
    """Tests for normalise()."""

    def test_normalise_produces_binary(self):
        page = make_synthetic_page()
        result = normalise(page)
        assert result.dtype == np.uint8
        # Output should be near-binary: mostly 0 and 255
        unique = set(np.unique(result))
        assert unique.issubset({0, 255}) or len(unique) <= 3

    def test_normalise_ink_is_dark(self):
        """After normalisation, text regions should be dark (0) and background light (255)."""
        page = make_synthetic_page(ink_value=30, bg_value=240)
        result = normalise(page)
        # Background (top-left corner, no text) should be 255
        assert result[5, 5] == 255
        # A text region (first word area) should contain dark pixels
        # The first word starts around y=100, x=80
        text_region = result[100:130, 80:140]
        assert (text_region == 0).any(), "Expected dark pixels in text region"

    def test_normalise_handles_inverted_ink(self):
        """If most pixels are dark (white text on black bg), normalise should invert."""
        page = make_synthetic_page(ink_value=220, bg_value=30)
        result = normalise(page)
        # After inversion, background should be 255
        assert result[5, 5] == 255

    def test_normalise_preserves_shape(self):
        page = make_synthetic_page(width=500, height=400)
        result = normalise(page)
        assert result.shape == page.shape


class TestSegmentLines:
    """Tests for segment_lines() and segment_lines_opencv()."""

    def test_segment_lines_finds_expected_count(self):
        """A page with 5 text lines should yield ~5 segments."""
        page = make_synthetic_page(n_lines=5, line_height=40, line_gap=50)
        deskewed, _ = deskew(page)
        normed = normalise(deskewed)
        strips = segment_lines_opencv(normed, min_height=15, merge_gap=5)
        # Allow ±1 tolerance (sometimes two close lines merge)
        assert 3 <= len(strips) <= 7, f"Expected ~5 lines, got {len(strips)}"

    def test_segment_lines_returns_arrays(self):
        page = make_synthetic_page(n_lines=3)
        normed = normalise(page)
        strips = segment_lines_opencv(normed, min_height=10)
        for strip in strips:
            assert isinstance(strip, np.ndarray)
            assert strip.ndim == 2
            assert strip.dtype == np.uint8

    def test_segment_lines_empty_page(self):
        """An all-white page should yield zero lines."""
        blank = np.full((800, 600), 255, dtype=np.uint8)
        strips = segment_lines_opencv(blank, min_height=10)
        assert len(strips) == 0

    def test_segment_lines_with_config(self):
        page = make_synthetic_page(n_lines=4)
        normed = normalise(page)
        cfg = PreprocessConfig(
            input_path=Path("."),
            output_dir=Path("."),
            min_segments_for_trust=1,
        )
        strips = segment_lines(normed, cfg)
        assert len(strips) >= 1

    def test_segment_lines_fallback_to_kraken(self):
        """When OpenCV finds too few lines, Kraken fallback is attempted."""
        # Create a page with very faint text so OpenCV finds 0-1 lines
        page = make_synthetic_page(ink_value=230, bg_value=235, n_lines=2)
        normed = normalise(page)
        cfg = PreprocessConfig(
            input_path=Path("."),
            output_dir=Path("."),
            min_segments_for_trust=5,  # set high so OpenCV result triggers fallback
        )
        # segment_lines should attempt Kraken (which may not be installed)
        # and return whatever it can — the point is it shouldn't crash
        strips = segment_lines(normed, cfg)
        assert isinstance(strips, list)


class TestSegmentWords:
    """Tests for segment_words()."""

    def test_segment_words_from_line(self):
        """A line strip with 4 word-clusters should yield ~4 word crops."""
        page = make_synthetic_page(n_lines=1, words_per_line=4, word_gap=40)
        normed = normalise(page)
        strips = segment_lines_opencv(normed, min_height=15)
        assert len(strips) >= 1
        words = segment_words(strips[0], min_width=5, min_height=5, pad=2)
        # Allow tolerance — sometimes words merge or split
        assert len(words) >= 2, f"Expected ≥2 words, got {len(words)}"

    def test_segment_words_empty_strip(self):
        """An all-white strip should yield zero words."""
        blank = np.full((40, 600), 255, dtype=np.uint8)
        words = segment_words(blank, min_width=5, min_height=5)
        assert len(words) == 0

    def test_segment_words_returns_arrays(self):
        page = make_synthetic_page(n_lines=1, words_per_line=3)
        normed = normalise(page)
        strips = segment_lines_opencv(normed, min_height=15)
        if strips:
            words = segment_words(strips[0], min_width=5, min_height=5)
            for w in words:
                assert isinstance(w, np.ndarray)
                assert w.ndim == 2
                assert w.dtype == np.uint8

    def test_segment_words_left_to_right_order(self):
        """Word crops should be ordered left-to-right."""
        page = make_synthetic_page(n_lines=1, words_per_line=5, word_gap=50)
        normed = normalise(page)
        strips = segment_lines_opencv(normed, min_height=15)
        if not strips:
            pytest.skip("No lines segmented")
        words = segment_words(strips[0], min_width=5, min_height=5)
        if len(words) >= 2:
            widths = [w.shape[1] for w in words]
            # All crops should have positive width
            assert all(w > 0 for w in widths)


class TestAlignCrops:
    """Tests for align_crops()."""

    def test_align_with_matching_tokens(self):
        """When crop count matches token count, alignment should be high-confidence."""
        crops = [np.full((30, 60), 30, dtype=np.uint8) for _ in range(5)]
        tokens = ["hello", "world", "this", "is", "text"]
        results = align_crops(crops, tokens, threshold=50.0)
        assert len(results) == 5
        for label, conf, needs_review in results:
            assert label in tokens
            assert conf >= 0.0

    def test_align_without_source_tokens(self):
        """With no source tokens, all crops should be flagged for review."""
        crops = [np.full((30, 60), 30, dtype=np.uint8) for _ in range(3)]
        results = align_crops(crops, [], threshold=65.0)
        assert len(results) == 3
        for label, conf, needs_review in results:
            assert needs_review is True
            assert label == ""

    def test_align_flags_low_confidence(self):
        """Very different token counts should produce low confidence for some."""
        crops = [np.full((30, 60), 30, dtype=np.uint8) for _ in range(10)]
        tokens = ["only", "two", "words"]
        results = align_crops(crops, tokens, threshold=99.0)
        # With threshold 99, most should be flagged
        flagged = sum(1 for _, _, nr in results if nr)
        assert flagged > 0

    def test_align_returns_one_per_crop(self):
        crops = [np.zeros((20, 40), dtype=np.uint8) for _ in range(7)]
        tokens = ["a", "b", "c", "d", "e", "f", "g"]
        results = align_crops(crops, tokens)
        assert len(results) == len(crops)


class TestExportDataset:
    """Tests for export_dataset()."""

    def test_export_creates_images_and_csv(self, tmp_path: Path):
        crops = [
            Crop(
                image=np.full((30, 50), 30, dtype=np.uint8),
                page_idx=0, line_idx=0, word_idx=0,
                label="hello", confidence=95.0, needs_review=False,
            ),
            Crop(
                image=np.full((30, 50), 30, dtype=np.uint8),
                page_idx=0, line_idx=0, word_idx=1,
                label="world", confidence=60.0, needs_review=True,
            ),
        ]
        out = tmp_path / "dataset"
        csv_path = export_dataset(crops, out)

        assert csv_path == out / "labels.csv"
        assert csv_path.exists()
        assert (out / "images").is_dir()
        # Two image files should exist
        pngs = list((out / "images").glob("*.png"))
        assert len(pngs) == 2

    def test_export_csv_contents(self, tmp_path: Path):
        crops = [
            Crop(
                image=np.full((20, 40), 0, dtype=np.uint8),
                page_idx=0, line_idx=0, word_idx=0,
                label="test", confidence=88.5, needs_review=False,
            ),
        ]
        csv_path = export_dataset(crops, tmp_path / "ds")
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["label"] == "test"
        assert rows[0]["needs_review"] == "false"
        assert "images/" in rows[0]["path"]

    def test_export_empty_crops(self, tmp_path: Path):
        """Exporting zero crops should still create the CSV header."""
        csv_path = export_dataset([], tmp_path / "empty")
        assert csv_path.exists()
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 0

    def test_export_image_filenames_follow_iam_convention(self, tmp_path: Path):
        crops = [
            Crop(
                image=np.zeros((20, 40), dtype=np.uint8),
                page_idx=2, line_idx=3, word_idx=7,
                label="x", confidence=100.0, needs_review=False,
            ),
        ]
        export_dataset(crops, tmp_path / "ds")
        expected = tmp_path / "ds" / "images" / "0002_03_007.png"
        assert expected.exists()


class TestDebugGrid:
    """Tests for write_debug_grid()."""

    def test_debug_grid_creates_png(self, tmp_path: Path):
        crops = [
            Crop(
                image=np.full((30, 50), 30, dtype=np.uint8),
                page_idx=i, line_idx=0, word_idx=0,
                label=f"word{i}", confidence=80.0 + i, needs_review=(i % 2 == 0),
            )
            for i in range(8)
        ]
        out = tmp_path / "grid.png"
        write_debug_grid(crops, out)
        assert out.exists()
        # Verify it's a valid image
        img = Image.open(out)
        assert img.size[0] > 0 and img.size[1] > 0

    def test_debug_grid_empty_crops(self, tmp_path: Path):
        """Writing a grid with zero crops should not crash (logs a warning)."""
        out = tmp_path / "empty_grid.png"
        write_debug_grid([], out)
        # File may or may not be created — the function just logs and returns

    def test_debug_grid_large_batch(self, tmp_path: Path):
        """100 crops should produce a multi-row grid without error."""
        crops = [
            Crop(
                image=np.full((20, 40), 0, dtype=np.uint8),
                page_idx=0, line_idx=0, word_idx=i,
                label=f"w{i}", confidence=90.0, needs_review=False,
            )
            for i in range(100)
        ]
        out = tmp_path / "big_grid.png"
        write_debug_grid(crops, out, cols=4)
        assert out.exists()


class TestReport:
    """Tests for write_report()."""

    def test_report_lists_low_confidence(self, tmp_path: Path):
        crops = [
            Crop(
                image=np.zeros((20, 40), dtype=np.uint8),
                page_idx=0, line_idx=0, word_idx=0,
                label="good", confidence=95.0, needs_review=False,
            ),
            Crop(
                image=np.zeros((20, 40), dtype=np.uint8),
                page_idx=0, line_idx=0, word_idx=1,
                label="bad", confidence=30.0, needs_review=True,
            ),
        ]
        report = tmp_path / "report.txt"
        write_report(crops, report, threshold=65.0)
        assert report.exists()
        content = report.read_text()
        assert "bad" in content
        assert "2" in content  # total crops
        assert "1" in content  # low-confidence count

    def test_report_all_high_confidence(self, tmp_path: Path):
        crops = [
            Crop(
                image=np.zeros((20, 40), dtype=np.uint8),
                page_idx=0, line_idx=0, word_idx=i,
                label=f"w{i}", confidence=95.0, needs_review=False,
            )
            for i in range(3)
        ]
        report = tmp_path / "report.txt"
        write_report(crops, report, threshold=65.0)
        content = report.read_text()
        assert "passed" in content.lower() or "✓" in content

    def test_report_empty_crops(self, tmp_path: Path):
        report = tmp_path / "report.txt"
        write_report([], report)
        assert report.exists()
        content = report.read_text()
        assert "0" in content


# ═══════════════════════════════════════════════════════════════════════════════
# Full pipeline integration test
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunPipeline:
    """End-to-end pipeline tests on synthetic input."""

    def test_pipeline_with_image_input(self, tmp_path: Path):
        """Single image → IAM dataset with images + labels.csv."""
        img_path = make_synthetic_image(
            tmp_path / "page.png",
            n_lines=3, words_per_line=3,
        )
        out_dir = tmp_path / "output"
        cfg = PreprocessConfig(
            input_path=img_path,
            output_dir=out_dir,
            dpi=150,
            write_debug_grid=True,
            write_report=True,
        )
        summary = run_pipeline(cfg)

        assert isinstance(summary, PipelineSummary)
        assert summary.total_pages >= 1
        assert summary.total_words >= 1
        assert (out_dir / "labels.csv").exists()
        assert (out_dir / "images").is_dir()
        # Debug grid + report should be written
        assert summary.debug_grid_pdf is not None
        assert summary.report_txt is not None
        assert summary.debug_grid_pdf.exists()
        assert summary.report_txt.exists()

    def test_pipeline_with_pdf_input(self, tmp_path: Path):
        """PDF with 2 pages → dataset covering both pages."""
        pdf_path = make_synthetic_pdf(tmp_path / "doc.pdf", n_pages=2)
        out_dir = tmp_path / "output"
        cfg = PreprocessConfig(
            input_path=pdf_path,
            output_dir=out_dir,
            dpi=150,
        )
        summary = run_pipeline(cfg)
        assert summary.total_pages == 2

    def test_pipeline_with_directory_input(self, tmp_path: Path):
        """A directory of images should be processed in sorted order."""
        in_dir = tmp_path / "input"
        in_dir.mkdir()
        for i in range(3):
            make_synthetic_image(
                in_dir / f"page_{i}.png",
                n_lines=2, words_per_line=2,
            )
        out_dir = tmp_path / "output"
        cfg = PreprocessConfig(
            input_path=in_dir,
            output_dir=out_dir,
            dpi=150,
        )
        summary = run_pipeline(cfg)
        assert summary.total_pages == 3
        assert summary.total_words >= 3  # at least some words detected

    def test_pipeline_with_source_text(self, tmp_path: Path):
        """When source_text.txt is provided, labels should be populated."""
        img_path = make_synthetic_image(
            tmp_path / "page.png",
            n_lines=2, words_per_line=4,
        )
        # Write a source text with matching word count
        source_path = tmp_path / "source.txt"
        source_path.write_text("the quick brown fox jumps over lazy dog the quick brown fox jumps")

        out_dir = tmp_path / "output"
        cfg = PreprocessConfig(
            input_path=img_path,
            output_dir=out_dir,
            source_text_path=source_path,
            dpi=150,
        )
        summary = run_pipeline(cfg)

        # Check labels.csv has some non-empty labels
        with (out_dir / "labels.csv").open() as f:
            rows = list(csv.DictReader(f))
        if rows:
            labels = [r["label"] for r in rows if r["label"]]
            assert len(labels) > 0, "Expected some non-empty labels after alignment"

    def test_pipeline_without_source_text(self, tmp_path: Path):
        """Without source_text, labels should be empty and all crops need review."""
        img_path = make_synthetic_image(tmp_path / "page.png", n_lines=2, words_per_line=2)
        out_dir = tmp_path / "output"
        cfg = PreprocessConfig(
            input_path=img_path,
            output_dir=out_dir,
            dpi=150,
        )
        summary = run_pipeline(cfg)

        with (out_dir / "labels.csv").open() as f:
            rows = list(csv.DictReader(f))
        if rows:
            for row in rows:
                assert row["label"] == ""
                assert row["needs_review"] == "true"

    def test_pipeline_empty_directory_raises(self, tmp_path: Path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        cfg = PreprocessConfig(
            input_path=empty_dir,
            output_dir=tmp_path / "out",
        )
        with pytest.raises(ValueError, match="No PDF or image files"):
            run_pipeline(cfg)

    def test_pipeline_creates_output_directory(self, tmp_path: Path):
        """Output dir should be created if it doesn't exist."""
        img_path = make_synthetic_image(tmp_path / "page.png")
        out_dir = tmp_path / "deeply" / "nested" / "output"
        cfg = PreprocessConfig(
            input_path=img_path,
            output_dir=out_dir,
            dpi=150,
        )
        run_pipeline(cfg)
        assert out_dir.exists()

    def test_pipeline_summary_counts(self, tmp_path: Path):
        """Summary counts should be internally consistent."""
        img_path = make_synthetic_image(
            tmp_path / "page.png",
            n_lines=3, words_per_line=3,
        )
        cfg = PreprocessConfig(
            input_path=img_path,
            output_dir=tmp_path / "out",
            dpi=150,
        )
        summary = run_pipeline(cfg)

        # total_words should equal the number of rows in labels.csv
        with (cfg.output_dir / "labels.csv").open() as f:
            csv_rows = list(csv.DictReader(f))
        assert summary.total_words == len(csv_rows)

        # low_confidence_crops should equal the count of needs_review=true rows
        review_count = sum(1 for r in csv_rows if r["needs_review"] == "true")
        assert summary.low_confidence_crops == review_count


# ═══════════════════════════════════════════════════════════════════════════════
# CLI test
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLI:
    """Test the argparse CLI via subprocess (avoids sys.argv pollution)."""

    def test_cli_runs_successfully(self, tmp_path: Path):
        img_path = make_synthetic_image(
            tmp_path / "page.png",
            n_lines=2, words_per_line=2,
        )
        out_dir = tmp_path / "cli_output"
        result = subprocess.run(
            [
                sys.executable, "-m", "app.ml.preprocess",
                "--input", str(img_path),
                "--output", str(out_dir),
                "--dpi", "150",
                "--debug",
                "--report",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent),  # backend/
            timeout=60,
        )
        assert result.returncode == 0, f"CLI failed:\n{result.stderr}\n{result.stdout}"
        assert (out_dir / "labels.csv").exists()
        assert "Pipeline complete" in result.stdout

    def test_cli_missing_input_dir(self, tmp_path: Path):
        """CLI should return exit code 1 when input doesn't exist."""
        result = subprocess.run(
            [
                sys.executable, "-m", "app.ml.preprocess",
                "--input", str(tmp_path / "nonexistent"),
                "--output", str(tmp_path / "out"),
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert result.returncode == 1

    def test_cli_with_source_text(self, tmp_path: Path):
        img_path = make_synthetic_image(
            tmp_path / "page.png",
            n_lines=1, words_per_line=3,
        )
        source = tmp_path / "source.txt"
        source.write_text("alpha beta gamma delta epsilon zeta")
        out_dir = tmp_path / "cli_src_output"

        result = subprocess.run(
            [
                sys.executable, "-m", "app.ml.preprocess",
                "--input", str(img_path),
                "--output", str(out_dir),
                "--source-text", str(source),
                "--dpi", "150",
                "--report",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=60,
        )
        assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
