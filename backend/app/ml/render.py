"""app/ml/render.py — Handwritten PDF rendering pipeline.

Takes a printed PDF and a trained model checkpoint, renders each word in
the writer's handwriting style, and assembles a new PDF with img2pdf.

Pipeline
--------
1.  Extract text blocks (headings, paragraphs), images, and page geometry
    from the source PDF via PyMuPDF ``page.get_text("dict")``.
2.  For each word in each line:
      a.  If the word is "supported" (basic Latin / accented chars), render
          it in the profile's handwriting style via the word renderer.
      b.  If the word contains unsupported symbols, or is part of an
          equation block, copy the original rendering from the source page.
3.  Normalize every rendered word to a target x-height so different font
    sizes in the original (headings vs body) are preserved proportionally.
4.  Apply configurable jitter (position), slant (rotation), and spacing
    variation to make the output look natural.
5.  Apply ink color and composite words onto a paper background
    (plain, ruled, or scan-texture).
6.  Paste original images from the source PDF onto the rendered page.
7.  Save each page as a PNG, then assemble all pages into a single PDF
    with img2pdf.

Progress
--------
``progress_cb`` is called with a float in [0, 1]:
  - 0.0 at start
  - Fractional updates per page and per block
  - 1.0 after the PDF is written

CLI usage
---------
    python -m app.ml.render \\
        --input  printed_doc.pdf \\
        --checkpoint checkpoints/profile-123/ \\
        --output  handwritten.pdf \\
        --paper-style ruled \\
        --ink-color "30,30,100"
"""

from __future__ import annotations

import argparse
import logging
import math
import random
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import fitz  # pymupdf
import img2pdf
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_DPI: int = 300
# x-height of body text at target DPI (pixels)
DEFAULT_TARGET_XHEIGHT_PX: int = 28
# Ink colour — dark blue-black
DEFAULT_INK_COLOR: tuple[int, int, int] = (35, 35, 90)
# Paper colour — slightly off-white
DEFAULT_PAPER_COLOR: tuple[int, int, int] = (252, 250, 246)
# Ruled-line colour — light blue-grey
DEFAULT_RULED_LINE_COLOR: tuple[int, int, int] = (200, 205, 220)
# Font size ratio above which a block is considered a heading (1.3x median)
HEADING_FONT_RATIO: float = 1.3
# Maximum cumulative horizontal drift from spacing variation (pixels)
MAX_DRIFT_PX: int = 30
# Characters considered "supported" for handwriting rendering
_SUPPORTED_RANGES = [
    (0x20, 0x7E),    # Basic ASCII printable
    (0xA0, 0xFF),    # Latin-1 Supplement (accented letters)
    (0x100, 0x17F),  # Latin Extended-A
    (0x180, 0x24F),  # Latin Extended-B
]
# Math / equation symbols that trigger equation-block detection
_MATH_SYMBOLS = set("∑∫√±×÷≤≥≠∞∂∇≈≡∝∈∉∪∩⊂⊃∀∃¬→←↔↑↓™°µαβγδεζηθικλμνξοπρστυφχψω")
# System font search paths for the synthetic renderer
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RenderConfig:
    """All tunables for a single render run."""

    dpi: int = DEFAULT_DPI
    target_xheight_px: int = DEFAULT_TARGET_XHEIGHT_PX

    # ── Ink ────────────────────────────────────────────────────────────────────
    ink_color: tuple[int, int, int] = DEFAULT_INK_COLOR

    # ── Paper ──────────────────────────────────────────────────────────────────
    paper_style: str = "plain"           # plain | ruled | scan_texture
    paper_color: tuple[int, int, int] = DEFAULT_PAPER_COLOR
    ruled_line_color: tuple[int, int, int] = DEFAULT_RULED_LINE_COLOR
    ruled_line_spacing_mm: float = 8.0
    scan_texture_strength: float = 4.0  # noise sigma for scan_texture

    # ── Handwriting variation ─────────────────────────────────────────────────
    jitter_x_px: float = 2.0            # ± random horizontal offset per word
    jitter_y_px: float = 1.5            # ± random vertical offset per word
    slant_range_deg: float = 5.0        # ± random rotation per word
    spacing_variation: float = 0.12     # ± fraction of word width between words
    char_rotation_deg: float = 3.0      # ± random rotation per character (synthetic)
    char_y_jitter_px: int = 2          # ± random vertical offset per character
    char_gap_px: int = 2               # base gap between characters

    # ── Layout ─────────────────────────────────────────────────────────────────
    margin_mm: float = 20.0
    line_height_factor: float = 1.6    # line spacing = xheight * factor

    # ── Reproducibility ────────────────────────────────────────────────────────
    seed: int | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WordInfo:
    """A single word extracted from the source PDF."""
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points
    font_size: float
    font_name: str
    is_heading: bool
    is_supported: bool

@dataclass
class LineInfo:
    """A text line containing one or more words."""
    words: list[WordInfo]
    bbox: tuple[float, float, float, float]

@dataclass
class BlockInfo:
    """A text block (paragraph or heading)."""
    lines: list[LineInfo]
    bbox: tuple[float, float, float, float]
    is_heading: bool
    is_equation: bool

@dataclass
class ImageInfo:
    """An image region on the page."""
    bbox: tuple[float, float, float, float]

@dataclass
class PageContent:
    """Everything extracted from one PDF page."""
    page_idx: int
    page_size_pt: tuple[float, float]  # width, height in PDF points
    blocks: list[BlockInfo]
    images: list[ImageInfo]
    median_font_size: float


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 1 — Text extraction
# ═══════════════════════════════════════════════════════════════════════════════

def _is_supported_char(ch: str) -> bool:
    """Return True if *ch* can be rendered in handwriting."""
    cp = ord(ch)
    for lo, hi in _SUPPORTED_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def _is_supported_word(text: str) -> bool:
    """Return True if every character in *text* is supported."""
    return bool(text) and all(_is_supported_char(ch) for ch in text)


def _is_equation_block(block_text: str, font_names: set[str]) -> bool:
    """Heuristic: detect equation blocks by math symbols or math font names."""
    if any(ch in _MATH_SYMBOLS for ch in block_text):
        return True
    for fn in font_names:
        fn_lower = fn.lower()
        if "math" in fn_lower or "symbol" in fn_lower or "cmsy" in fn_lower:
            return True
    return False


def _split_span_to_words(
    span_text: str,
    span_bbox: tuple[float, float, float, float],
    span_size: float,
    span_font: str,
    is_heading: bool,
) -> list[WordInfo]:
    """Split a text span into individual WordInfo objects.

    Positions are estimated by distributing the span width proportionally
    across words based on character count.
    """
    words = span_text.split()
    if not words:
        return []

    x0, y0, x1, y1 = span_bbox
    total_chars = sum(len(w) for w in words) + len(words) - 1  # include spaces
    if total_chars == 0:
        return []

    scale = (x1 - x0) / total_chars
    result: list[WordInfo] = []
    cursor_x = x0

    for word in words:
        word_w = len(word) * scale
        word_bbox = (cursor_x, y0, cursor_x + word_w, y1)
        result.append(WordInfo(
            text=word,
            bbox=word_bbox,
            font_size=span_size,
            font_name=span_font,
            is_heading=is_heading,
            is_supported=_is_supported_word(word),
        ))
        cursor_x += word_w + scale  # +1 space char width

    return result


def extract_page_content(
    page: fitz.Page,
    page_idx: int,
) -> PageContent:
    """Extract text blocks, images, and geometry from a PDF page.

    Parameters
    ----------
    page:
        A PyMuPDF page object.
    page_idx:
        Zero-based page index.

    Returns
    -------
    PageContent with blocks (text), images, and page size.
    """
    page_rect = page.rect
    page_size_pt = (page_rect.width, page_rect.height)
    page_dict = page.get_text("dict")

    # ── Collect all font sizes to find the median ─────────────────────────────
    all_sizes: list[float] = []
    for block in page_dict.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                all_sizes.append(float(span.get("size", 12)))

    median_size = sorted(all_sizes)[len(all_sizes) // 2] if all_sizes else 12.0

    # ── Build blocks ──────────────────────────────────────────────────────────
    blocks: list[BlockInfo] = []
    images: list[ImageInfo] = []

    for raw_block in page_dict.get("blocks", []):
        block_type = raw_block.get("type", 0)
        block_bbox = tuple(raw_block.get("bbox", (0, 0, 0, 0)))

        if block_type == 1:
            # Image block
            images.append(ImageInfo(bbox=block_bbox))
            continue

        if block_type != 0:
            continue

        # Text block
        block_text_parts: list[str] = []
        block_font_names: set[str] = set()
        lines: list[LineInfo] = []

        for raw_line in raw_block.get("lines", []):
            line_bbox = tuple(raw_line.get("bbox", (0, 0, 0, 0)))
            line_words: list[WordInfo] = []

            for span in raw_line.get("spans", []):
                span_text = span.get("text", "")
                span_size = float(span.get("size", 12))
                span_font = span.get("font", "unknown")
                span_bbox = tuple(span.get("bbox", (0, 0, 0, 0)))

                block_text_parts.append(span_text)
                block_font_names.add(span_font)

                is_heading = span_size > median_size * HEADING_FONT_RATIO
                line_words.extend(
                    _split_span_to_words(span_text, span_bbox, span_size, span_font, is_heading)
                )

            if line_words:
                lines.append(LineInfo(words=line_words, bbox=line_bbox))

        if not lines:
            continue

        block_text = " ".join(block_text_parts)
        is_eq = _is_equation_block(block_text, block_font_names)
        is_heading = any(w.is_heading for w in lines[0].words) if lines else False

        blocks.append(BlockInfo(
            lines=lines,
            bbox=block_bbox,
            is_heading=is_heading,
            is_equation=is_eq,
        ))

    # ── Also collect images via get_images for completeness ────────────────────
    try:
        for img_info in page.get_image_info():
            bbox = img_info.get("bbox", None)
            if bbox:
                images.append(ImageInfo(bbox=tuple(bbox)))
    except Exception:
        pass  # get_image_info not available in all PyMuPDF versions

    return PageContent(
        page_idx=page_idx,
        page_size_pt=page_size_pt,
        blocks=blocks,
        images=images,
        median_font_size=median_size,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 2 — Paper backgrounds
# ═══════════════════════════════════════════════════════════════════════════════

def create_paper_background(
    size_px: tuple[int, int],
    cfg: RenderConfig,
) -> Image.Image:
    """Create a paper background image of the given pixel dimensions.

    Parameters
    ----------
    size_px:
        (width, height) in pixels.
    cfg:
        Render configuration — determines paper_style, colors, texture.

    Returns
    -------
    PIL RGB image.
    """
    w, h = size_px
    bg = Image.new("RGB", (w, h), color=cfg.paper_color)

    if cfg.paper_style == "ruled":
        _apply_ruled_lines(bg, cfg)
    elif cfg.paper_style == "scan_texture":
        _apply_scan_texture(bg, cfg)
    elif cfg.paper_style == "plain":
        pass  # just the solid color
    else:
        logger.warning("Unknown paper_style '%s' — using plain.", cfg.paper_style)

    return bg


def _apply_ruled_lines(img: Image.Image, cfg: RenderConfig) -> None:
    """Draw horizontal ruled lines on *img* (in-place)."""
    draw = ImageDraw.Draw(img)
    w = img.width
    spacing_px = int(cfg.ruled_line_spacing_mm * cfg.dpi / 25.4)
    margin_px = int(cfg.margin_mm * cfg.dpi / 25.4)

    y = margin_px
    while y < img.height - margin_px:
        draw.line(
            [(margin_px // 2, y), (w - margin_px // 2, y)],
            fill=cfg.ruled_line_color,
            width=1,
        )
        y += spacing_px


def _apply_scan_texture(img: Image.Image, cfg: RenderConfig) -> None:
    """Add Gaussian noise to simulate scanner artefacts (in-place)."""
    arr = np.asarray(img, dtype=np.float32)
    noise = np.random.normal(0, cfg.scan_texture_strength, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    blurred = Image.fromarray(arr, "RGB").filter(ImageFilter.GaussianBlur(radius=0.4))
    img.paste(blurred)


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 3 — Word rendering
# ═══════════════════════════════════════════════════════════════════════════════

class WordRenderer(Protocol):
    """Interface for word image generation."""

    def render_word(self, word: str, target_xheight_px: int) -> np.ndarray:
        """Return a greyscale uint8 image (0=ink, 255=background) for *word*."""
        ...


def _find_system_font() -> str | None:
    """Return the path to the first available system font, or None."""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


class SyntheticWordRenderer:
    """Fallback renderer that produces handwriting-like images using PIL.

    Each character is rendered individually with slight random rotation and
    vertical offset, then composited into a word.  This won't look exactly
    like real handwriting but exercises the full pipeline.
    """

    def __init__(self, cfg: RenderConfig, rng: random.Random) -> None:
        self.cfg = cfg
        self.rng = rng
        self._font_path = _find_system_font()
        # Cache: font_size -> ImageFont
        self._font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if size not in self._font_cache:
            if self._font_path:
                self._font_cache[size] = ImageFont.truetype(self._font_path, size)
            else:
                self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    def render_word(self, word: str, target_xheight_px: int) -> np.ndarray:
        """Render *word* as a greyscale image at the given x-height.

        Parameters
        ----------
        word:
            The word text to render.
        target_xheight_px:
            Desired x-height in pixels.  The font size is chosen so that
            the lowercase 'x' height matches this value.

        Returns
        -------
        np.ndarray uint8, shape (H, W), 0=ink, 255=background.
        """
        # DejaVu Sans x-height ≈ 0.53 * font_size
        font_size = max(8, int(target_xheight_px / 0.53))
        font = self._get_font(font_size)

        # Render each character individually for handwriting-like variation
        char_images: list[Image.Image] = []
        for ch in word:
            char_img = self._render_char(ch, font, font_size)
            char_images.append(char_img)

        if not char_images:
            return np.full((target_xheight_px, target_xheight_px * 2), 255, dtype=np.uint8)

        # Composite characters with variable spacing
        gap = self.cfg.char_gap_px
        total_width = sum(img.width for img in char_images) + gap * (len(char_images) - 1)
        max_height = max(img.height for img in char_images)

        word_img = Image.new("L", (total_width + 4, max_height + 4), 255)
        x = 2
        for char_img in char_images:
            y_off = self.rng.randint(-self.cfg.char_y_jitter_px, self.cfg.char_y_jitter_px)
            y = max(0, (max_height - char_img.height) // 2 + y_off + 2)
            word_img.paste(char_img, (x, y))
            x += char_img.width + gap

        return np.asarray(word_img, dtype=np.uint8)

    def _render_char(self, ch: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
                     font_size: int) -> Image.Image:
        """Render a single character with slight random rotation."""
        pad = font_size
        temp = Image.new("L", (font_size * 3 + pad, font_size * 3 + pad), 255)
        draw = ImageDraw.Draw(temp)

        # Draw the character
        draw.text((font_size, font_size), ch, fill=0, font=font)

        # Crop to character bounds
        bbox = temp.getbbox()
        if not bbox:
            return Image.new("L", (font_size // 2, font_size), 255)
        cropped = temp.crop(bbox)

        # Apply slight random rotation
        angle = self.rng.uniform(-self.cfg.char_rotation_deg, self.cfg.char_rotation_deg)
        if abs(angle) > 0.1:
            cropped = cropped.rotate(angle, expand=True, fillcolor=255, resample=Image.BICUBIC)

        return cropped


class ModelWordRenderer:
    """Renders words using a trained handwriting model checkpoint.

    Attempts to load the model from *checkpoint_path*.  If loading fails
    (torch not installed, checkpoint missing, model code is a stub), the
    caller should fall back to SyntheticWordRenderer.
    """

    def __init__(self, checkpoint_path: Path, cfg: RenderConfig) -> None:
        self.cfg = cfg
        self.checkpoint_path = checkpoint_path
        self._model = None
        self._load()

    def _load(self) -> None:
        """Load the model from the checkpoint directory."""
        # Find the checkpoint file
        ckpt_file: Path | None = None
        if self.checkpoint_path.is_file():
            ckpt_file = self.checkpoint_path
        elif self.checkpoint_path.is_dir():
            # Look for .pth, .pt, or .ckpt files
            for pattern in ("*.pth", "*.pt", "*.ckpt", "model.*"):
                matches = list(self.checkpoint_path.glob(pattern))
                if matches:
                    ckpt_file = matches[0]
                    break

        if ckpt_file is None or not ckpt_file.exists():
            raise FileNotFoundError(f"No checkpoint found at '{self.checkpoint_path}'.")

        # Try to import torch and the model
        try:
            import torch  # noqa: F401
            from app.services.hw_models.factory import get_model  # noqa: F401
            # If we get here, torch and the model code are available.
            # The actual model loading depends on the specific architecture.
            # For now, we delegate to the factory, but since train_profile()
            # is still a stub, the checkpoint won't have valid weights.
            # This will raise a RuntimeError or similar when trying to load.
            raise NotImplementedError(
                "Model-based word rendering requires a trained checkpoint. "
                "The training stub has not been replaced yet."
            )
        except ImportError as exc:
            raise ImportError(
                f"Cannot load model: missing dependency ({exc})."
            ) from exc

    def render_word(self, word: str, target_xheight_px: int) -> np.ndarray:
        """Generate *word* in the writer's handwriting style."""
        raise NotImplementedError(
            "ModelWordRenderer.render_word() requires a trained model."
        )


def get_word_renderer(
    checkpoint_path: Path,
    cfg: RenderConfig,
    rng: random.Random,
) -> WordRenderer:
    """Return a word renderer — tries model first, falls back to synthetic."""
    # Only attempt model rendering if checkpoint exists
    if checkpoint_path and checkpoint_path.exists():
        try:
            renderer = ModelWordRenderer(checkpoint_path, cfg)
            # Test it with a simple word
            renderer.render_word("test", 20)
            logger.info("Using ModelWordRenderer (checkpoint: %s).", checkpoint_path)
            return renderer
        except Exception as exc:
            logger.warning(
                "ModelWordRenderer unavailable (%s) — falling back to synthetic.", exc
            )

    logger.info("Using SyntheticWordRenderer (no trained model available).")
    return SyntheticWordRenderer(cfg, rng)


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 4 — Image processing (x-height, slant, ink color)
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_xheight(
    word_img: np.ndarray,
    target_xheight_px: int,
) -> np.ndarray:
    """Scale *word_img* so its height matches approximately *target_xheight_px*.

    The word image height is roughly 1.6x the x-height (cap height + descenders).
    We scale the total height to target_xheight_px * 1.6.
    """
    if word_img.size == 0:
        return word_img

    current_h = word_img.shape[0]
    if current_h == 0:
        return word_img

    target_h = max(4, int(target_xheight_px * 1.6))
    if current_h == target_h:
        return word_img

    scale = target_h / current_h
    new_w = max(1, int(word_img.shape[1] * scale))
    new_h = target_h

    pil = Image.fromarray(word_img)
    pil = pil.resize((new_w, new_h), Image.LANCZOS)
    return np.asarray(pil, dtype=np.uint8)


def apply_slant(
    word_img: np.ndarray,
    max_slant_deg: float,
    rng: random.Random,
) -> np.ndarray:
    """Apply a random slant (rotation) to *word_img*."""
    angle = rng.uniform(-max_slant_deg, max_slant_deg)
    if abs(angle) < 0.1:
        return word_img

    pil = Image.fromarray(word_img)
    # Rotate with expand to avoid clipping, filling with background (255)
    pil = pil.rotate(angle, expand=True, fillcolor=255, resample=Image.BICUBIC)
    return np.asarray(pil, dtype=np.uint8)


def apply_ink_color(
    word_img: np.ndarray,
    ink_color: tuple[int, int, int],
) -> Image.Image:
    """Convert a greyscale word image to an RGBA image with the given ink color.

    The ink intensity from the greyscale image becomes the alpha channel,
    so anti-aliased edges blend smoothly with the paper.
    """
    # word_img: 0=ink, 255=background
    # alpha: 255 where ink is darkest, 0 where background
    alpha = (255 - word_img).astype(np.uint8)
    h, w = word_img.shape

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = ink_color[0]
    rgba[:, :, 1] = ink_color[1]
    rgba[:, :, 2] = ink_color[2]
    rgba[:, :, 3] = alpha

    return Image.fromarray(rgba, "RGBA")


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 5 — Original page rendering (for images, equations, unsupported words)
# ═══════════════════════════════════════════════════════════════════════════════

def render_original_page(page: fitz.Page, dpi: int) -> np.ndarray:
    """Render an entire PDF page at *dpi* and return it as an RGB numpy array.

    Used to extract original images, equation blocks, and unsupported symbols
    that should be preserved as-is in the handwritten output.
    """
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    if pix.n >= 3:
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        arr = arr[:, :, :3]  # take RGB only
    else:
        # Grayscale → convert to RGB
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        arr = np.stack([gray, gray, gray], axis=-1)

    return arr.copy()


def crop_region(
    orig_img: np.ndarray,
    bbox_pt: tuple[float, float, float, float],
    dpi: int,
) -> np.ndarray:
    """Crop a region from *orig_img* given a bbox in PDF points.

    Returns an RGB numpy array.  If the bbox is invalid, returns a 1x1 black pixel.
    """
    x0, y0, x1, y1 = bbox_pt
    scale = dpi / 72.0
    px0 = max(0, int(x0 * scale))
    py0 = max(0, int(y0 * scale))
    px1 = min(orig_img.shape[1], int(x1 * scale))
    py1 = min(orig_img.shape[0], int(y1 * scale))

    if px1 <= px0 or py1 <= py0:
        return np.zeros((1, 1, 3), dtype=np.uint8)

    return orig_img[py0:py1, px0:px1].copy()


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 6 — Page composition
# ═══════════════════════════════════════════════════════════════════════════════

def _pt_to_px(pt_val: float, dpi: int) -> int:
    """Convert PDF points to pixels at the given DPI."""
    return int(pt_val * dpi / 72.0)


def composite_page(
    paper: Image.Image,
    content: PageContent,
    renderer: WordRenderer,
    orig_page_img: np.ndarray,
    cfg: RenderConfig,
    rng: random.Random,
) -> Image.Image:
    """Composite rendered words, original images, and equations onto *paper*.

    Parameters
    ----------
    paper:
        The paper background image (RGB, modified in-place).
    content:
        Extracted page content (text blocks, images).
    renderer:
        Word renderer (model or synthetic).
    orig_page_img:
        The original page rendered at cfg.dpi (for copying images/equations).
    cfg:
        Render configuration.
    rng:
        Random number generator for jitter/slant/spacing.

    Returns
    -------
    The modified *paper* image.
    """
    scale = cfg.dpi / 72.0

    for block in content.blocks:
        if block.is_equation:
            # Keep the original rendering for equation blocks
            crop = crop_region(orig_page_img, block.bbox, cfg.dpi)
            _paste_rgb(paper, crop, block.bbox, scale)
            continue

        for line in block.lines:
            cumulative_drift = 0.0

            for word in line.words:
                if not word.is_supported:
                    # Keep original rendering for unsupported words
                    crop = crop_region(orig_page_img, word.bbox, cfg.dpi)
                    _paste_rgb(paper, crop, word.bbox, scale)
                    continue

                # ── Calculate target x-height ───────────────────────────────
                size_ratio = word.font_size / max(content.median_font_size, 1)
                target_xh = max(8, int(cfg.target_xheight_px * size_ratio))

                # ── Render the word ──────────────────────────────────────────
                word_img = renderer.render_word(word.text, target_xh)
                word_img = normalize_xheight(word_img, target_xh)

                # ── Apply slant ──────────────────────────────────────────────
                word_img = apply_slant(word_img, cfg.slant_range_deg, rng)

                # ── Calculate position ───────────────────────────────────────
                x0, y0, x1, y1 = word.bbox
                # Baseline ≈ 80% from top of the text bbox
                baseline_y = y0 + (y1 - y0) * 0.8

                # Position in pixels
                pos_x = int(x0 * scale) + int(rng.uniform(-cfg.jitter_x_px, cfg.jitter_x_px))
                pos_y = int(baseline_y * scale) - int(word_img.shape[0] * 0.9)

                # ── Apply spacing variation ──────────────────────────────────
                word_w = word_img.shape[1]
                extra_space = rng.uniform(-cfg.spacing_variation, cfg.spacing_variation) * word_w
                cumulative_drift += extra_space
                cumulative_drift = max(-MAX_DRIFT_PX, min(MAX_DRIFT_PX, cumulative_drift))
                pos_x += int(cumulative_drift)

                # ── Apply ink color and paste ────────────────────────────────
                colored = apply_ink_color(word_img, cfg.ink_color)
                # Ensure we don't paste outside the page
                _paste_rgba(paper, colored, (pos_x, pos_y))

    # ── Paste original images ──────────────────────────────────────────────
    for img_info in content.images:
        crop = crop_region(orig_page_img, img_info.bbox, cfg.dpi)
        _paste_rgb(paper, crop, img_info.bbox, scale)

    return paper


def _paste_rgba(base: Image.Image, overlay: Image.Image, pos: tuple[int, int]) -> None:
    """Paste an RGBA image onto an RGB base, clipping to bounds."""
    x, y = pos
    # Clip negative positions
    if x < 0:
        overlay = overlay.crop((-x, 0, overlay.width, overlay.height))
        x = 0
    if y < 0:
        overlay = overlay.crop((0, -y, overlay.width, overlay.height))
        y = 0
    # Clip if extending beyond the base
    if x + overlay.width > base.width:
        overlay = overlay.crop((0, 0, base.width - x, overlay.height))
    if y + overlay.height > base.height:
        overlay = overlay.crop((0, 0, overlay.width, base.height - y))
    if overlay.width <= 0 or overlay.height <= 0:
        return
    base.paste(overlay, (x, y), overlay)


def _paste_rgb(base: Image.Image, crop: np.ndarray, bbox_pt: tuple[float, ...],
               scale: float) -> None:
    """Paste an RGB numpy crop onto *base* at the position given by *bbox_pt*."""
    if crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        return
    x0, y0 = bbox_pt[0], bbox_idx_1(bbox_pt)
    pos_x = int(x0 * scale)
    pos_y = int(y0 * scale)
    pil_crop = Image.fromarray(crop, "RGB")
    _paste_rgba(base, pil_crop.convert("RGBA"), (pos_x, pos_y))


def bbox_idx_1(bbox: tuple[float, ...]) -> float:
    """Extract y0 from a bbox tuple (helper for readability)."""
    return bbox[1]


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 7 — PDF export via img2pdf
# ═══════════════════════════════════════════════════════════════════════════════

def save_pages_as_pdf(
    page_images: list[Image.Image],
    output_path: Path,
    dpi: int,
) -> None:
    """Assemble a list of page images into a single PDF using img2pdf.

    Each page image is saved to a temporary PNG file, then img2pdf converts
    them all into one PDF.  Temp files are cleaned up afterwards.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / ".render_tmp"
    temp_dir.mkdir(exist_ok=True)

    temp_files: list[str] = []
    try:
        for idx, img in enumerate(page_images):
            # Ensure RGB mode
            if img.mode != "RGB":
                img = img.convert("RGB")
            temp_path = temp_dir / f"page_{idx:04d}.png"
            img.save(temp_path, format="PNG", dpi=(dpi, dpi))
            temp_files.append(str(temp_path))

        with output_path.open("wb") as f:
            f.write(img2pdf.convert(temp_files))

        logger.info("PDF written to '%s' (%d pages).", output_path, len(page_images))
    finally:
        for tf in temp_files:
            try:
                Path(tf).unlink()
            except FileNotFoundError:
                pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def render_pdf(
    input_pdf_path: Path,
    checkpoint_path: Path,
    output_pdf_path: Path,
    progress_cb: Callable[[float], None] | None = None,
    cfg: RenderConfig | None = None,
) -> None:
    """Render a printed PDF as a handwritten PDF.

    Parameters
    ----------
    input_pdf_path:
        Path to the source printed PDF.
    checkpoint_path:
        Path to the trained model checkpoint (file or directory).
        If the checkpoint is unavailable, a synthetic renderer is used.
    output_pdf_path:
        Where to write the resulting handwritten PDF.
    progress_cb:
        Optional callback called with a float in [0, 1].
    cfg:
        Optional RenderConfig.  If None, defaults are used.
    """
    if cfg is None:
        cfg = RenderConfig()
    if progress_cb is None:
        progress_cb = lambda _: None

    # ── Validate inputs ────────────────────────────────────────────────────────
    if not input_pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(cfg.seed)
    renderer = get_word_renderer(checkpoint_path, cfg, rng)

    progress_cb(0.0)

    doc = fitz.open(str(input_pdf_path))
    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        # Write an empty PDF
        save_pages_as_pdf([], output_pdf_path, cfg.dpi)
        progress_cb(1.0)
        return

    page_images: list[Image.Image] = []

    for page_idx in range(total_pages):
        # ── Progress: start of page ──────────────────────────────────────────
        page_frac = page_idx / total_pages
        progress_cb(page_frac + 0.01)

        page = doc[page_idx]
        content = extract_page_content(page, page_idx)

        # ── Render original page for images/equations/unsupported ───────────────
        orig_page_img = render_original_page(page, cfg.dpi)

        # ── Create paper background ───────────────────────────────────────────
        page_w_px = int(content.page_size_pt[0] * cfg.dpi / 72)
        page_h_px = int(content.page_size_pt[1] * cfg.dpi / 72)
        paper = create_paper_background((page_w_px, page_h_px), cfg)

        # ── Composite everything ──────────────────────────────────────────────
        composite_page(paper, content, renderer, orig_page_img, cfg, rng)
        page_images.append(paper)

        # ── Progress: end of page ────────────────────────────────────────────
        progress_cb(page_frac + (1 / total_pages) * 0.8)

    doc.close()

    # ── Export to PDF ───────────────────────────────────────────────────────
    progress_cb(0.95)
    save_pages_as_pdf(page_images, output_pdf_path, cfg.dpi)
    progress_cb(1.0)

    logger.info(
        "render_pdf complete: %d page(s) → '%s'.",
        total_pages,
        output_pdf_path,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_color(s: str) -> tuple[int, int, int]:
    """Parse 'r,g,b' string into a tuple of ints."""
    parts = s.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"Expected 'r,g,b', got '{s}'.")
    return tuple(int(p.strip()) for p in parts)  # type: ignore[return-value]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.ml.render",
        description="Render a printed PDF as a handwritten PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", "-i", required=True, type=Path, help="Source printed PDF.")
    p.add_argument("--checkpoint", "-c", required=True, type=Path, help="Trained model checkpoint (dir or file).")
    p.add_argument("--output", "-o", required=True, type=Path, help="Output handwritten PDF.")
    p.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"Render DPI (default: {DEFAULT_DPI}).")
    p.add_argument("--target-xheight", type=int, default=DEFAULT_TARGET_XHEIGHT_PX,
                   help=f"Target x-height in pixels (default: {DEFAULT_TARGET_XHEIGHT_PX}).")
    p.add_argument("--paper-style", choices=["plain", "ruled", "scan_texture"],
                   default="plain", help="Paper background style.")
    p.add_argument("--ink-color", type=_parse_color, default=DEFAULT_INK_COLOR,
                   help="Ink color as 'r,g,b' (default: dark blue-black).")
    p.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Logging verbosity.")
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = RenderConfig(
        dpi=args.dpi,
        target_xheight_px=args.target_xheight,
        paper_style=args.paper_style,
        ink_color=args.ink_color,
        seed=args.seed,
    )

    progress_vals: list[float] = []

    def _progress(p: float) -> None:
        progress_vals.append(p)
        if int(p * 100) % 10 == 0:
            print(f"  Rendering… {int(p * 100)}%")

    try:
        render_pdf(
            input_pdf_path=args.input,
            checkpoint_path=args.checkpoint,
            output_pdf_path=args.output,
            progress_cb=_progress,
            cfg=cfg,
        )
    except Exception as exc:
        logger.error("Render failed: %s", exc, exc_info=True)
        return 1

    print(textwrap.dedent(f"""\
        ✓ Render complete
          Input      : {args.input}
          Output     : {args.output}
          Pages      : {len(progress_vals)}
          Paper      : {args.paper_style}
          DPI        : {args.dpi}
        """))
    return 0


if __name__ == "__main__":
    sys.exit(main())
