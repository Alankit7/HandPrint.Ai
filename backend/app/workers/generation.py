"""generation.py — background task that runs the full PDF → handwriting pipeline.

This function is called by the queue (thread or RQ worker).  It:
  1. Loads style samples.
  2. Rasterises the input PDF into line images.
  3. Renders each line through the handwriting model.
  4. Assembles the output PDF.
  5. Updates job state throughout.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.models.job import JobStatus
from app.services.hw_models.factory import get_model
from app.services.job_store import job_store
from app.services.pdf_pipeline import line_images_to_pdf, pdf_to_line_images

logger = logging.getLogger(__name__)


def run_generation(job_id: str, pdf_path: str, sample_paths: list[str]) -> None:
    """Entry point for the background worker.  Never raises — all errors are
    captured and stored in the job state so the client can poll for them.
    """
    try:
        _run(job_id, Path(pdf_path), [Path(p) for p in sample_paths])
    except Exception as exc:
        logger.exception("Generation failed for job %s: %s", job_id, exc)
        try:
            job_store.update(
                job_id,
                status=JobStatus.FAILED,
                error=str(exc),
                message="Generation failed — see error field",
            )
        except Exception:
            pass  # job may no longer exist; ignore


def _run(job_id: str, pdf_path: Path, sample_paths: list[Path]) -> None:
    logger.info("[%s] Starting generation | pdf=%s samples=%d", job_id, pdf_path.name, len(sample_paths))
    job_store.update(job_id, status=JobStatus.PROCESSING, progress=0.0, message="Loading style samples…")

    # ── 1. Load style reference images ───────────────────────────────────────
    sample_imgs: list[Image.Image] = []
    for sp in sample_paths:
        if not sp.exists():
            raise FileNotFoundError(f"Sample file not found: {sp}")
        sample_imgs.append(Image.open(sp).convert("L"))

    if not sample_imgs:
        raise ValueError("No style sample images provided")

    # ── 2. Condition the model on this writer's style ─────────────────────────
    job_store.update(job_id, progress=0.05, message="Conditioning model on handwriting style…")
    model = get_model()
    model.set_style(sample_imgs)

    # ── 3. Rasterise input PDF → line images ──────────────────────────────────
    job_store.update(job_id, progress=0.1, message="Analysing PDF…")
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {pdf_path}")

    line_tuples = pdf_to_line_images(pdf_path, img_height_px=settings.img_height)
    if not line_tuples:
        raise ValueError("No text lines found in the uploaded PDF")

    source_lines = [img for _, _, img in line_tuples]
    total = len(source_lines)
    logger.info("[%s] %d lines to render", job_id, total)

    # ── 4. Render each line ───────────────────────────────────────────────────
    rendered: list[Image.Image] = []

    def _progress(done: int, _total: int) -> None:
        pct = 0.1 + 0.8 * (done / _total)
        job_store.update(
            job_id,
            progress=pct,
            message=f"Rendering line {done}/{_total}…",
        )

    rendered = model.render_lines(source_lines, progress_callback=_progress)

    # ── 5. Assemble output PDF ────────────────────────────────────────────────
    job_store.update(job_id, progress=0.9, message="Assembling output PDF…")
    output_path = settings.output_dir / f"{job_id}.pdf"
    line_images_to_pdf(rendered, output_path)

    # ── 6. Mark done ──────────────────────────────────────────────────────────
    job_store.update(
        job_id,
        status=JobStatus.DONE,
        progress=1.0,
        message="Done",
        output_path=str(output_path),
    )
    logger.info("[%s] Generation complete → %s", job_id, output_path)
