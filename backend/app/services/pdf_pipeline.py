"""PDF ↔ image pipeline.

Responsibilities:
  1. Rasterise every page of the input PDF into line-level PIL images.
  2. Reassemble a list of rendered line images into an A4 output PDF.
"""

from __future__ import annotations

import logging
import textwrap
from io import BytesIO
from pathlib import Path
from typing import Generator

import fitz  # pymupdf
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
DPI = 150                 # rasterisation resolution
PAGE_WIDTH_MM = 210       # A4
PAGE_HEIGHT_MM = 297
MARGIN_MM = 15
LINE_SPACING_MM = 2       # gap between rendered handwriting lines


# ── Page → line images ────────────────────────────────────────────────────────

def pdf_to_line_images(
    pdf_path: Path,
    img_height_px: int = 64,
) -> list[tuple[int, int, Image.Image]]:
    """
    Rasterise *pdf_path* and segment each page into text-line images.

    Returns a flat list of (page_index, line_index, pil_image).
    The image height is normalised to *img_height_px*; width scales proportionally.
    """
    doc = fitz.open(str(pdf_path))
    results: list[tuple[int, int, Image.Image]] = []
    zoom = DPI / 72  # fitz default is 72 dpi
    mat = fitz.Matrix(zoom, zoom)

    for page_idx, page in enumerate(doc):
        # 1. Rasterise full page
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        page_img = Image.frombytes("L", (pix.width, pix.height), pix.samples)

        # 2. Extract text blocks to find line bounding boxes
        blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,bno,btype)
        if not blocks:
            logger.debug("Page %d has no text blocks, skipping", page_idx)
            continue

        for line_idx, block in enumerate(blocks):
            x0, y0, x1, y1, text, *_ = block
            if not text.strip():
                continue

            # Scale bounding box from PDF points to pixel space
            px0 = int(x0 * zoom)
            py0 = int(y0 * zoom)
            px1 = int(x1 * zoom)
            py1 = int(y1 * zoom)

            # Add a small vertical padding
            pad = max(4, int((py1 - py0) * 0.1))
            py0 = max(0, py0 - pad)
            py1 = min(page_img.height, py1 + pad)

            if px1 <= px0 or py1 <= py0:
                continue

            line_crop = page_img.crop((px0, py0, px1, py1))

            # Normalise height
            orig_w, orig_h = line_crop.size
            if orig_h == 0:
                continue
            new_w = max(1, int(orig_w * img_height_px / orig_h))
            line_crop = line_crop.resize((new_w, img_height_px), Image.LANCZOS)
            results.append((page_idx, line_idx, line_crop))

    doc.close()
    logger.info(
        "PDF '%s' → %d line images (DPI=%d)", pdf_path.name, len(results), DPI
    )
    return results


# ── Line images → output PDF ──────────────────────────────────────────────────

def line_images_to_pdf(
    line_images: list[Image.Image],
    output_path: Path,
    page_width_mm: float = PAGE_WIDTH_MM,
    page_height_mm: float = PAGE_HEIGHT_MM,
    margin_mm: float = MARGIN_MM,
    line_spacing_mm: float = LINE_SPACING_MM,
) -> Path:
    """
    Stack *line_images* top-to-bottom onto A4 pages and save to *output_path*.

    Each image is scaled to fit horizontally within the margins;
    a new page is started whenever there is not enough vertical space.
    Returns *output_path*.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    page_w = page_width_mm * mm
    page_h = page_height_mm * mm
    margin = margin_mm * mm
    spacing = line_spacing_mm * mm
    usable_w = page_w - 2 * margin

    buf = BytesIO()
    c = canvas.Canvas(str(output_path), pagesize=(page_w, page_h))
    y_cursor = page_h - margin  # reportlab y grows upward

    def _start_new_page() -> float:
        c.showPage()
        return page_h - margin

    for img in line_images:
        img_w_px, img_h_px = img.size
        # Scale to fit usable width
        scale = usable_w / img_w_px
        draw_w = usable_w
        draw_h = img_h_px * scale

        if y_cursor - draw_h - spacing < margin:
            y_cursor = _start_new_page()

        # Convert PIL → bytes for reportlab
        img_buf = BytesIO()
        img_rgb = img.convert("RGB")
        img_rgb.save(img_buf, format="PNG")
        img_buf.seek(0)

        y_top = y_cursor - draw_h
        c.drawInlineImage(
            img_rgb,  # reportlab also accepts PIL images directly
            margin,
            y_top,
            width=draw_w,
            height=draw_h,
        )
        y_cursor = y_top - spacing

    c.save()
    logger.info("Output PDF written to '%s'", output_path)
    return output_path
