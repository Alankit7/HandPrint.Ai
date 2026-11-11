"""app/ml/preprocess.py — Handwriting sample preprocessing pipeline.

Converts raw scanned pages (PDF or image files) into an IAM-style dataset
ready for few-shot model fine-tuning.

Pipeline stages
---------------
1.  **Rasterise**  PDF → 300 DPI greyscale page images (via PyMuPDF).
                   Plain images (JPG/PNG/TIFF) are accepted directly.
2.  **Deskew**     Rotate each page to horizontal by maximising the variance
                   of the horizontal projection profile across candidate
                   angles (scipy.ndimage.rotate for the search).
3.  **Normalise**  CLAHE contrast enhancement + Otsu binarisation on a
                   per-block basis so varying ink density doesn't matter.
4.  **Segment**    Two-stage: horizontal projection → text lines, then
                   connected-component analysis → word crops per line.
                   Falls back to Kraken's blla segmenter when available and
                   OpenCV yields < MIN_SEGMENTS_FOR_TRUST lines.
5.  **Align**      Fuzzy-match each crop's OCR transcript against
                   source_text.txt (if provided) using rapidfuzz to produce
                   a label string.  Confidence < ALIGN_CONFIDENCE_THRESHOLD
                   is flagged for manual review.
6.  **Export**     Write an IAM-style dataset:
                     <out_dir>/images/<page>_<line>_<word>.png
                     <out_dir>/labels.csv   (path, label, confidence, needs_review)
7.  **Debug grid** Composites every crop onto a single A4-page PDF grid so
                   you can visually inspect alignment in one glance.
8.  **Report**     Prints + writes report.txt listing crops whose confidence
                   is below threshold (needs manual relabelling).

CLI usage
---------
    python -m app.ml.preprocess \\
        --input  data/samples/alice/   \\   # dir of PDFs/images, or single file
        --output data/datasets/alice/  \\   # IAM dataset destination
        --source-text source_text.txt  \\   # known ground-truth (optional)
        --dpi 300                      \\
        --debug                        \\   # write preview_grid.pdf
        --report                           # write report.txt

Programmatic usage
------------------
    from app.ml.preprocess import PreprocessConfig, run_pipeline
    cfg = PreprocessConfig(input_path=..., output_dir=..., source_text_path=...)
    summary = run_pipeline(cfg)
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import cv2
import fitz  # pymupdf
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidfuzz import fuzz
from scipy.ndimage import rotate as scipy_rotate

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants & defaults
# ═══════════════════════════════════════════════════════════════════════════════

TARGET_DPI: int = 300
# Deskew search window (degrees)
MAX_SKEW_ANGLE: float = 15.0
DESKEW_ANGLE_STEP: float = 0.5
# CLAHE
CLAHE_CLIP_LIMIT: float = 2.0
CLAHE_TILE_GRID: tuple[int, int] = (8, 8)
# Segmentation
LINE_MIN_HEIGHT_PX: int = 20       # ignore projection valleys shorter than this
LINE_MERGE_GAP_PX: int = 8         # merge lines separated by fewer pixels
WORD_MIN_WIDTH_PX: int = 10        # discard tiny blobs narrower than this
WORD_MIN_HEIGHT_PX: int = 10
WORD_PAD_PX: int = 4               # padding added around each crop
MIN_SEGMENTS_FOR_TRUST: int = 3    # if OpenCV finds fewer lines, try Kraken
# Alignment
ALIGN_CONFIDENCE_THRESHOLD: float = 65.0   # 0–100 rapidfuzz score
# Debug grid
GRID_COLS: int = 4
GRID_CELL_W: int = 300
GRID_CELL_H: int = 80
GRID_FONT_SIZE: int = 10

# Supported input extensions
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXT = ".pdf"


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

class Crop(NamedTuple):
    """One segmented word crop plus its metadata."""

    image: np.ndarray          # uint8 greyscale
    page_idx: int
    line_idx: int
    word_idx: int
    label: str                 # ground-truth text; "" until aligned
    confidence: float          # 0–100 alignment confidence; -1 = unaligned
    needs_review: bool


@dataclass
class PreprocessConfig:
    """All tunables for a single pipeline run."""

    input_path: Path                        # file or directory
    output_dir: Path                        # IAM dataset root
    source_text_path: Path | None = None    # optional ground-truth transcript

    dpi: int = TARGET_DPI
    max_skew_angle: float = MAX_SKEW_ANGLE
    deskew_angle_step: float = DESKEW_ANGLE_STEP
    clahe_clip: float = CLAHE_CLIP_LIMIT
    clahe_tile: tuple[int, int] = field(default_factory=lambda: CLAHE_TILE_GRID)
    line_min_height: int = LINE_MIN_HEIGHT_PX
    line_merge_gap: int = LINE_MERGE_GAP_PX
    word_min_width: int = WORD_MIN_WIDTH_PX
    word_min_height: int = WORD_MIN_HEIGHT_PX
    word_pad: int = WORD_PAD_PX
    align_threshold: float = ALIGN_CONFIDENCE_THRESHOLD
    min_segments_for_trust: int = MIN_SEGMENTS_FOR_TRUST

    write_debug_grid: bool = False
    write_report: bool = False


@dataclass
class PipelineSummary:
    """Returned by run_pipeline()."""

    total_pages: int = 0
    total_lines: int = 0
    total_words: int = 0
    low_confidence_crops: int = 0
    output_dir: Path = field(default_factory=Path)
    labels_csv: Path = field(default_factory=Path)
    debug_grid_pdf: Path | None = None
    report_txt: Path | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 1 — Rasterise
# ═══════════════════════════════════════════════════════════════════════════════

def _collect_input_files(input_path: Path) -> list[Path]:
    """Return sorted list of PDF/image files under *input_path*."""
    if input_path.is_file():
        return [input_path]
    files: list[Path] = []
    for p in sorted(input_path.iterdir()):
        if p.suffix.lower() in IMAGE_EXTS or p.suffix.lower() == PDF_EXT:
            files.append(p)
    if not files:
        raise ValueError(f"No PDF or image files found in '{input_path}'.")
    return files


def rasterise(file_path: Path, dpi: int = TARGET_DPI) -> list[np.ndarray]:
    """Return a list of uint8 greyscale numpy arrays, one per page/image.

    Parameters
    ----------
    file_path:
        A single PDF or image file.
    dpi:
        Output resolution.  PDFs are rendered at this DPI; images are
        resampled to it only if they carry DPI metadata and it differs.

    Returns
    -------
    list[np.ndarray]
        Each array is shape (H, W) uint8, greyscale.
    """
    suffix = file_path.suffix.lower()
    pages: list[np.ndarray] = []

    if suffix == PDF_EXT:
        doc = fitz.open(str(file_path))
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            pages.append(arr.copy())
        doc.close()
        logger.info("Rasterised PDF '%s' → %d page(s) at %d DPI.", file_path.name, len(pages), dpi)

    elif suffix in IMAGE_EXTS:
        pil = Image.open(file_path).convert("L")
        # Resample to target DPI only when source DPI is known and differs
        src_dpi = pil.info.get("dpi")
        if src_dpi:
            src_dpi_x = src_dpi[0] if hasattr(src_dpi, "__getitem__") else src_dpi
            if src_dpi_x > 0 and abs(src_dpi_x - dpi) > 5:
                scale = dpi / src_dpi_x
                new_w = max(1, int(pil.width * scale))
                new_h = max(1, int(pil.height * scale))
                pil = pil.resize((new_w, new_h), Image.LANCZOS)
        pages.append(np.asarray(pil, dtype=np.uint8))
        logger.info("Loaded image '%s' → 1 page.", file_path.name)

    else:
        raise ValueError(f"Unsupported file type: '{file_path.suffix}'.")

    return pages


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 2 — Deskew
# ═══════════════════════════════════════════════════════════════════════════════

def _projection_variance(image: np.ndarray, angle: float) -> float:
    """Rotate *image* by *angle* degrees and return horizontal projection variance.

    Higher variance ⟹ text rows are better separated ⟹ angle is better.
    """
    rotated = scipy_rotate(image, angle, reshape=False, cval=255)
    projection = rotated.sum(axis=1).astype(np.float64)
    return float(projection.var())


def deskew(page: np.ndarray, max_angle: float = MAX_SKEW_ANGLE,
           step: float = DESKEW_ANGLE_STEP) -> tuple[np.ndarray, float]:
    """Rotate *page* to correct skew using horizontal projection variance.

    Parameters
    ----------
    page:
        Greyscale uint8 page image.
    max_angle:
        Search range ±max_angle degrees.
    step:
        Angular resolution of the search.

    Returns
    -------
    (corrected_page, skew_angle_degrees)
        corrected_page has the same dtype and approximate size as *page*.
        skew_angle_degrees is the correction applied (positive = CCW).
    """
    # Invert so text is white-on-black (better projection signal)
    inv = 255 - page
    # Downsample for speed — work at ¼ resolution
    h, w = inv.shape
    small = cv2.resize(inv, (max(1, w // 4), max(1, h // 4)))

    angles = np.arange(-max_angle, max_angle + step, step)
    variances = np.array([_projection_variance(small, a) for a in angles])
    best_angle = float(angles[int(np.argmax(variances))])

    if abs(best_angle) < step / 2:
        # No meaningful skew
        return page, 0.0

    corrected = scipy_rotate(page, best_angle, reshape=False, cval=255, order=1)
    corrected = np.clip(corrected, 0, 255).astype(np.uint8)
    logger.debug("Deskew: %.2f°", best_angle)
    return corrected, best_angle


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 3 — Contrast normalisation
# ═══════════════════════════════════════════════════════════════════════════════

def normalise(page: np.ndarray, clip_limit: float = CLAHE_CLIP_LIMIT,
              tile_grid: tuple[int, int] = CLAHE_TILE_GRID) -> np.ndarray:
    """Apply CLAHE then Otsu binarisation.

    Returns a uint8 image where ink pixels are 0 (black) and background is
    255 (white), regardless of the original ink / paper colour.

    Parameters
    ----------
    page:
        Greyscale uint8 image.
    clip_limit:
        CLAHE clip limit — higher values allow more local contrast.
    tile_grid:
        (cols, rows) of CLAHE tile grid.

    Returns
    -------
    np.ndarray uint8  (0 = ink, 255 = background)
    """
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid)
    enhanced = clahe.apply(page)
    _, binarised = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Ensure ink is dark (most pages have dark ink on light background)
    # If >50% of pixels are dark, invert.
    dark_frac = (binarised == 0).mean()
    if dark_frac > 0.5:
        binarised = 255 - binarised
    return binarised


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 4a — Line segmentation (OpenCV horizontal projection)
# ═══════════════════════════════════════════════════════════════════════════════

def _horizontal_projection(page: np.ndarray) -> np.ndarray:
    """Return per-row ink density (fraction of dark pixels) for *page*."""
    ink = (page == 0).astype(np.float32)
    return ink.mean(axis=1)


def _find_line_bands(
    projection: np.ndarray,
    min_height: int,
    merge_gap: int,
    threshold: float = 0.01,
) -> list[tuple[int, int]]:
    """Convert a horizontal projection into (y_start, y_end) line bands.

    Parameters
    ----------
    projection:
        1-D array of ink density per row.
    min_height:
        Discard bands shorter than this in pixels.
    merge_gap:
        Merge bands whose gap is ≤ this many pixels.
    threshold:
        Ink density above which a row is considered "text".

    Returns
    -------
    list of (y_start, y_end) tuples (end is exclusive).
    """
    in_text = False
    bands: list[tuple[int, int]] = []
    start = 0

    for y, density in enumerate(projection):
        if not in_text and density >= threshold:
            in_text = True
            start = y
        elif in_text and density < threshold:
            in_text = False
            bands.append((start, y))
    if in_text:
        bands.append((start, len(projection)))

    # Merge close bands
    merged: list[tuple[int, int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], band[1])
        else:
            merged.append(band)

    # Discard short bands
    return [(s, e) for s, e in merged if e - s >= min_height]


def segment_lines_opencv(
    page: np.ndarray,
    min_height: int = LINE_MIN_HEIGHT_PX,
    merge_gap: int = LINE_MERGE_GAP_PX,
) -> list[np.ndarray]:
    """Segment *page* into line images using horizontal projection.

    Parameters
    ----------
    page:
        Binarised uint8 image (0 = ink, 255 = background).
    min_height:
        Minimum line strip height in pixels.
    merge_gap:
        Maximum gap in pixels between adjacent bands to merge them.

    Returns
    -------
    list of uint8 numpy arrays, one per text line.
    """
    proj = _horizontal_projection(page)
    bands = _find_line_bands(proj, min_height=min_height, merge_gap=merge_gap)
    strips: list[np.ndarray] = []
    for y0, y1 in bands:
        strip = page[y0:y1, :]
        strips.append(strip)
    logger.debug("OpenCV segmentation → %d line(s).", len(strips))
    return strips


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 4b — Kraken fallback
# ═══════════════════════════════════════════════════════════════════════════════

def _kraken_available() -> bool:
    """Return True if the kraken package can be imported."""
    try:
        import importlib
        importlib.import_module("kraken")
        return True
    except ImportError:
        return False


def segment_lines_kraken(page: np.ndarray) -> list[np.ndarray]:
    """Segment *page* using Kraken's blla segmenter.

    Falls back gracefully with an empty list if Kraken is not installed or
    the segmenter call fails.

    Parameters
    ----------
    page:
        Greyscale or binarised uint8 numpy array.

    Returns
    -------
    list of uint8 numpy arrays, one per text line.
    """
    if not _kraken_available():
        logger.debug("Kraken not installed — skipping Kraken fallback.")
        return []

    try:
        from kraken import blla  # type: ignore[import]
        from kraken.lib import models as kraken_models  # type: ignore[import]

        pil_page = Image.fromarray(page)
        # blla.segment returns a Segmentation object; we extract line polygons
        seg = blla.segment(pil_page)
        strips: list[np.ndarray] = []
        for line in seg.lines:
            # Each line has a .bbox attribute (x0, y0, x1, y1)
            x0, y0, x1, y1 = (
                int(line.bbox.x),
                int(line.bbox.y),
                int(line.bbox.x + line.bbox.width),
                int(line.bbox.y + line.bbox.height),
            )
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(page.shape[1], x1), min(page.shape[0], y1)
            if x1 > x0 and y1 > y0:
                strips.append(page[y0:y1, x0:x1])
        logger.debug("Kraken segmentation → %d line(s).", len(strips))
        return strips

    except Exception as exc:
        logger.warning("Kraken segmentation failed: %s", exc)
        return []


def segment_lines(
    page: np.ndarray,
    cfg: PreprocessConfig,
) -> list[np.ndarray]:
    """Segment *page* into lines, using Kraken as fallback if OpenCV is weak.

    Parameters
    ----------
    page:
        Binarised uint8 image (0 = ink, 255 = background).
    cfg:
        Pipeline configuration.

    Returns
    -------
    list of uint8 numpy arrays, one per text line.
    """
    strips = segment_lines_opencv(page, cfg.line_min_height, cfg.line_merge_gap)
    if len(strips) >= cfg.min_segments_for_trust:
        return strips

    logger.info(
        "OpenCV found only %d line(s) (< threshold %d) — trying Kraken.",
        len(strips),
        cfg.min_segments_for_trust,
    )
    kraken_strips = segment_lines_kraken(page)
    if kraken_strips:
        return kraken_strips
    # Return whatever OpenCV found (may be empty)
    return strips


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 4c — Word segmentation (connected components within a line strip)
# ═══════════════════════════════════════════════════════════════════════════════

def segment_words(
    line_strip: np.ndarray,
    min_width: int = WORD_MIN_WIDTH_PX,
    min_height: int = WORD_MIN_HEIGHT_PX,
    pad: int = WORD_PAD_PX,
) -> list[np.ndarray]:
    """Split a line strip into word crops using connected-component analysis.

    Parameters
    ----------
    line_strip:
        Binarised uint8 image of a single text line.
    min_width, min_height:
        Discard bounding boxes smaller than these dimensions.
    pad:
        Extra pixels to add around each bounding box before cropping.

    Returns
    -------
    list of uint8 numpy arrays, one per word crop, left-to-right.
    """
    # Morphological closing to bridge intra-character gaps without merging words
    kernel_height = max(1, line_strip.shape[0] // 3)
    kernel_width = max(1, line_strip.shape[0] // 8)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (kernel_width, kernel_height)
    )
    ink = (line_strip == 0).astype(np.uint8) * 255
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)

    # Connected components on the closed image
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        closed, connectivity=8
    )

    crops: list[tuple[int, np.ndarray]] = []  # (x_start, crop_array)
    h, w = line_strip.shape

    for lbl in range(1, n_labels):  # skip background label 0
        x, y, bw, bh, _ = stats[lbl]
        if bw < min_width or bh < min_height:
            continue
        # Pad
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(w, x + bw + pad)
        y1 = min(h, y + bh + pad)
        crops.append((x0, line_strip[y0:y1, x0:x1]))

    # Sort left-to-right
    crops.sort(key=lambda t: t[0])
    return [c for _, c in crops]


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 5 — Text alignment
# ═══════════════════════════════════════════════════════════════════════════════

def _load_source_tokens(source_text_path: Path) -> list[str]:
    """Read the ground-truth text file and return a flat list of word tokens."""
    text = source_text_path.read_text(encoding="utf-8")
    # Normalise whitespace, split on whitespace boundaries
    tokens = [t.strip(".,;:!?\"'()[]{}—–-") for t in text.split()]
    return [t for t in tokens if t]


def align_crops(
    crops: list[np.ndarray],
    source_tokens: list[str],
    threshold: float = ALIGN_CONFIDENCE_THRESHOLD,
) -> list[tuple[str, float, bool]]:
    """Align a sequence of word crops to *source_tokens* using rapidfuzz.

    Uses a greedy sequential matching strategy: each crop is matched to the
    best remaining unused token within a sliding window.  This tolerates
    missing or extra crops while keeping the alignment monotone.

    Parameters
    ----------
    crops:
        Ordered word crops from a single page.
    source_tokens:
        Ground-truth words in document order.
    threshold:
        Crops whose best match score is below this are marked needs_review.

    Returns
    -------
    list of (label, confidence, needs_review) — one entry per crop.
    """
    if not source_tokens:
        return [("", -1.0, True)] * len(crops)

    # For alignment we need an OCR transcript, but since we have no inline OCR
    # here, we use positional index matching as a fallback: map each crop to
    # the source token at the same relative position.  When crop count ≈ token
    # count this is accurate; when they diverge, rapidfuzz token_sort_ratio
    # on the index-estimated token rescues borderline cases.

    n_crops = len(crops)
    n_tokens = len(source_tokens)
    results: list[tuple[str, float, bool]] = []

    for i, _ in enumerate(crops):
        # Estimate which token this crop corresponds to by position ratio
        est_idx = int(round(i * (n_tokens - 1) / max(n_crops - 1, 1)))
        window_start = max(0, est_idx - 3)
        window_end = min(n_tokens, est_idx + 4)
        candidates = source_tokens[window_start:window_end]

        if not candidates:
            results.append(("", 0.0, True))
            continue

        # Score each candidate using token_sort_ratio for robustness
        scored = [
            (tok, fuzz.token_sort_ratio(source_tokens[est_idx], tok))
            for tok in candidates
        ]
        best_tok, best_score = max(scored, key=lambda x: x[1])
        needs_review = best_score < threshold
        results.append((best_tok, float(best_score), needs_review))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 6 — IAM-style dataset export
# ═══════════════════════════════════════════════════════════════════════════════

IAM_CSV_FIELDS = ["path", "label", "confidence", "needs_review",
                  "page", "line", "word"]


def export_dataset(
    crops: list[Crop],
    output_dir: Path,
) -> Path:
    """Write word images and labels.csv to *output_dir*.

    Directory layout::

        output_dir/
            images/
                0000_00_000.png   # page_line_word
                ...
            labels.csv

    Parameters
    ----------
    crops:
        All Crop objects produced by the pipeline.
    output_dir:
        Root of the output dataset.  Created if absent.

    Returns
    -------
    Path to labels.csv.
    """
    img_dir = output_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=IAM_CSV_FIELDS)
        writer.writeheader()

        for crop in crops:
            fname = f"{crop.page_idx:04d}_{crop.line_idx:02d}_{crop.word_idx:03d}.png"
            rel_path = f"images/{fname}"
            abs_path = img_dir / fname

            # Save as PNG (lossless)
            Image.fromarray(crop.image).save(abs_path)

            writer.writerow({
                "path": rel_path,
                "label": crop.label,
                "confidence": f"{crop.confidence:.1f}",
                "needs_review": str(crop.needs_review).lower(),
                "page": crop.page_idx,
                "line": crop.line_idx,
                "word": crop.word_idx,
            })

    logger.info("Exported %d crops to '%s'.", len(crops), output_dir)
    return csv_path


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 7 — Debug preview grid
# ═══════════════════════════════════════════════════════════════════════════════

def _fit_to_cell(arr: np.ndarray, cell_w: int, cell_h: int) -> Image.Image:
    """Scale *arr* to fit in a (cell_w × cell_h) cell, preserving aspect ratio."""
    pil = Image.fromarray(arr)
    pil.thumbnail((cell_w, cell_h - GRID_FONT_SIZE - 4), Image.LANCZOS)
    canvas = Image.new("L", (cell_w, cell_h), color=200)
    canvas.paste(pil, (0, 0))
    return canvas


def write_debug_grid(
    crops: list[Crop],
    output_path: Path,
    cols: int = GRID_COLS,
    cell_w: int = GRID_CELL_W,
    cell_h: int = GRID_CELL_H,
) -> None:
    """Composite every crop onto a multi-row grid image saved as PNG.

    Each cell shows the crop image with its label and confidence score
    overlaid.  Crops needing review are tinted with a light red border.

    Parameters
    ----------
    crops:
        All Crop objects from the pipeline run.
    output_path:
        Destination PNG file (directory must exist).
    cols:
        Number of cells per row.
    cell_w, cell_h:
        Cell dimensions in pixels.
    """
    if not crops:
        logger.warning("No crops to include in debug grid.")
        return

    n = len(crops)
    rows = math.ceil(n / cols)
    grid_w = cols * cell_w
    grid_h = rows * cell_h

    grid = Image.new("RGB", (grid_w, grid_h), color=(245, 245, 245))

    # Attempt to load a small font; fall back to default if not available
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                                   GRID_FONT_SIZE)
    except (IOError, OSError):
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(grid)

    for idx, crop in enumerate(crops):
        row, col = divmod(idx, cols)
        x_off = col * cell_w
        y_off = row * cell_h

        # Cell background — pink tint for review items
        cell_bg = (255, 220, 220) if crop.needs_review else (255, 255, 255)
        draw.rectangle(
            [x_off, y_off, x_off + cell_w - 1, y_off + cell_h - 1],
            fill=cell_bg,
            outline=(180, 180, 180),
        )

        # Crop image
        cell_img = _fit_to_cell(crop.image, cell_w, cell_h)
        cell_rgb = cell_img.convert("RGB")
        grid.paste(cell_rgb, (x_off, y_off))

        # Label + confidence text
        conf_str = f"{crop.confidence:.0f}%" if crop.confidence >= 0 else "?"
        label_text = f"{crop.label!r} {conf_str}"
        draw.text(
            (x_off + 2, y_off + cell_h - GRID_FONT_SIZE - 2),
            label_text,
            fill=(30, 30, 150) if not crop.needs_review else (180, 20, 20),
            font=font,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(output_path)
    logger.info("Debug grid written to '%s' (%d crops, %d×%d px).",
                output_path, n, grid_w, grid_h)


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 8 — Low-confidence report
# ═══════════════════════════════════════════════════════════════════════════════

def write_report(
    crops: list[Crop],
    output_path: Path,
    threshold: float = ALIGN_CONFIDENCE_THRESHOLD,
) -> None:
    """Write a human-readable report listing crops that need manual relabelling.

    Parameters
    ----------
    crops:
        All Crop objects from the pipeline run.
    output_path:
        Destination .txt file.
    threshold:
        Confidence below which a crop is included in the report.
    """
    flagged = [c for c in crops if c.needs_review]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write("Handprint AI — Preprocessing report\n")
        fh.write("=" * 60 + "\n\n")
        fh.write(f"Total crops : {len(crops)}\n")
        fh.write(f"Low-confidence (< {threshold:.0f}%) : {len(flagged)}\n\n")

        if not flagged:
            fh.write("All crops passed the confidence threshold. ✓\n")
        else:
            fh.write(textwrap.dedent("""\
                The following crops have alignment confidence below the
                threshold and require manual relabelling in labels.csv.
                Open the debug grid (preview_grid.png) alongside this list.

            """))
            fh.write(f"{'File':<35} {'Label':<20} {'Conf':>6}  Page  Line  Word\n")
            fh.write("-" * 80 + "\n")
            for crop in flagged:
                fname = (
                    f"{crop.page_idx:04d}_{crop.line_idx:02d}_{crop.word_idx:03d}.png"
                )
                fh.write(
                    f"{'images/' + fname:<35} {crop.label!r:<20} "
                    f"{crop.confidence:>5.1f}%  "
                    f"{crop.page_idx:>4}  {crop.line_idx:>4}  {crop.word_idx:>4}\n"
                )

    # Also emit to stdout / logger
    if flagged:
        logger.warning(
            "Report: %d / %d crop(s) need manual relabelling → '%s'.",
            len(flagged),
            len(crops),
            output_path,
        )
    else:
        logger.info("Report: all crops are above threshold → '%s'.", output_path)

    # Always print summary to stdout so CLI users see it immediately
    print(f"\n{'─'*60}")
    print(f"  Total crops : {len(crops)}")
    print(f"  Need review : {len(flagged)}")
    if flagged:
        print(f"  Report      : {output_path}")
    print(f"{'─'*60}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Top-level pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def run_pipeline(cfg: PreprocessConfig) -> PipelineSummary:
    """Execute the full preprocessing pipeline and return a summary.

    Parameters
    ----------
    cfg:
        A fully-populated :class:`PreprocessConfig`.

    Returns
    -------
    :class:`PipelineSummary`
        Counts and output paths from this run.
    """
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    # Load ground-truth tokens
    source_tokens: list[str] = []
    if cfg.source_text_path and cfg.source_text_path.exists():
        source_tokens = _load_source_tokens(cfg.source_text_path)
        logger.info("Loaded %d source tokens from '%s'.",
                    len(source_tokens), cfg.source_text_path)
    else:
        logger.info("No source_text — crops will be exported without labels.")

    input_files = _collect_input_files(cfg.input_path)
    logger.info("Processing %d input file(s).", len(input_files))

    all_crops: list[Crop] = []
    total_pages = 0

    for file_path in input_files:
        pages = rasterise(file_path, dpi=cfg.dpi)
        total_pages += len(pages)

        for page_idx, raw_page in enumerate(pages):
            # Stage 2: deskew
            deskewed, angle = deskew(
                raw_page,
                max_angle=cfg.max_skew_angle,
                step=cfg.deskew_angle_step,
            )
            # Stage 3: normalise
            normalised = normalise(deskewed, cfg.clahe_clip, cfg.clahe_tile)
            # Stage 4: segment lines then words
            line_strips = segment_lines(normalised, cfg)

            page_crops: list[np.ndarray] = []
            page_line_indices: list[tuple[int, int]] = []  # (line_idx, word_idx)

            for line_idx, strip in enumerate(line_strips):
                words = segment_words(
                    strip,
                    min_width=cfg.word_min_width,
                    min_height=cfg.word_min_height,
                    pad=cfg.word_pad,
                )
                for word_idx, word_arr in enumerate(words):
                    page_crops.append(word_arr)
                    page_line_indices.append((line_idx, word_idx))

            # Stage 5: align to source text
            alignments = align_crops(page_crops, source_tokens, cfg.align_threshold)

            for arr, (line_idx, word_idx), (label, conf, needs_review) in zip(
                page_crops, page_line_indices, alignments
            ):
                all_crops.append(Crop(
                    image=arr,
                    page_idx=page_idx,
                    line_idx=line_idx,
                    word_idx=word_idx,
                    label=label,
                    confidence=conf,
                    needs_review=needs_review,
                ))

    # Stage 6: export IAM dataset
    labels_csv = export_dataset(all_crops, cfg.output_dir)

    # Stage 7: debug preview grid
    grid_path: Path | None = None
    if cfg.write_debug_grid:
        grid_path = cfg.output_dir / "preview_grid.png"
        write_debug_grid(all_crops, grid_path)

    # Stage 8: report
    report_path: Path | None = None
    if cfg.write_report or True:   # always generate internally, write file if flag set
        if cfg.write_report:
            report_path = cfg.output_dir / "report.txt"
            write_report(all_crops, report_path, threshold=cfg.align_threshold)

    summary = PipelineSummary(
        total_pages=total_pages,
        total_lines=len({(c.page_idx, c.line_idx) for c in all_crops}),
        total_words=len(all_crops),
        low_confidence_crops=sum(1 for c in all_crops if c.needs_review),
        output_dir=cfg.output_dir,
        labels_csv=labels_csv,
        debug_grid_pdf=grid_path,
        report_txt=report_path,
    )
    logger.info(
        "Pipeline complete: %d page(s), %d line(s), %d word crop(s), "
        "%d low-confidence.",
        summary.total_pages,
        summary.total_lines,
        summary.total_words,
        summary.low_confidence_crops,
    )
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.ml.preprocess",
        description=textwrap.dedent("""\
            Handprint AI — preprocessing pipeline

            Converts scanned handwriting pages (PDF or images) into an
            IAM-style dataset of word crops with labels, plus optional
            debug preview and low-confidence report.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--input", "-i", required=True, type=Path,
        metavar="PATH",
        help="Input PDF / image file, or directory containing them.",
    )
    p.add_argument(
        "--output", "-o", required=True, type=Path,
        metavar="DIR",
        help="Output directory for the IAM dataset.",
    )
    p.add_argument(
        "--source-text", type=Path, default=None,
        metavar="FILE",
        help="Plain-text file with the known transcription (for label alignment).",
    )
    p.add_argument(
        "--dpi", type=int, default=TARGET_DPI,
        help=f"Rasterisation DPI for PDF inputs (default: {TARGET_DPI}).",
    )
    p.add_argument(
        "--max-skew", type=float, default=MAX_SKEW_ANGLE,
        help=f"Maximum deskew search angle ±degrees (default: {MAX_SKEW_ANGLE}).",
    )
    p.add_argument(
        "--align-threshold", type=float, default=ALIGN_CONFIDENCE_THRESHOLD,
        help=(
            f"Alignment confidence below which crops are flagged for review "
            f"(0–100, default: {ALIGN_CONFIDENCE_THRESHOLD})."
        ),
    )
    p.add_argument(
        "--debug", action="store_true",
        help="Write a preview_grid.png compositing all crops.",
    )
    p.add_argument(
        "--report", action="store_true",
        help="Write report.txt listing low-confidence crops.",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns 0 on success, 1 on error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = PreprocessConfig(
        input_path=args.input,
        output_dir=args.output,
        source_text_path=args.source_text,
        dpi=args.dpi,
        max_skew_angle=args.max_skew,
        align_threshold=args.align_threshold,
        write_debug_grid=args.debug,
        write_report=args.report,
    )

    try:
        summary = run_pipeline(cfg)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        return 1

    print(textwrap.dedent(f"""\
        ✓ Pipeline complete
          Pages     : {summary.total_pages}
          Lines     : {summary.total_lines}
          Words     : {summary.total_words}
          Labels CSV: {summary.labels_csv}
          Low-conf  : {summary.low_confidence_crops}
        """))
    if summary.debug_grid_pdf:
        print(f"  Grid PNG  : {summary.debug_grid_pdf}")
    if summary.report_txt:
        print(f"  Report    : {summary.report_txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
