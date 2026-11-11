"""ML stub interfaces.

These two functions are the ONLY entry points the rest of the codebase calls
into the ML layer.  Replace the bodies with real model code when ready;
everything else (workers, API, tests) stays unchanged.

Contracts
---------
train_profile(profile_id, sample_dir, checkpoint_out_dir, progress_cb)
    Fine-tunes the handwriting model on the sample images.
    *progress_cb* is called with a float in [0, 1] as training progresses.
    Must write a model checkpoint to *checkpoint_out_dir* on success.
    Raises any exception on failure — the worker will catch it.

render_pdf(input_pdf_path, checkpoint_path, output_pdf_path, progress_cb)
    Renders *input_pdf_path* in the writer's style using *checkpoint_path*.
    *progress_cb* is called with a float in [0, 1] as rendering progresses.
    Must write the finished PDF to *output_pdf_path*.
    Raises any exception on failure — the worker will catch it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable


ProgressCallback = Callable[[float], None]


def train_profile(
    profile_id: str,
    sample_dir: Path,
    checkpoint_out_dir: Path,
    progress_cb: ProgressCallback,
) -> None:
    """Fine-tune the handwriting model on *sample_dir* for *profile_id*.

    Replace this stub with real training code (One-DM, DiffusionPen, etc.).

    Parameters
    ----------
    profile_id:
        Unique identifier of the Profile being trained (useful for logging).
    sample_dir:
        Directory containing 15–30 greyscale handwriting sample images.
    checkpoint_out_dir:
        Directory where the trained checkpoint should be saved.
        Will exist and be writable by the time this function is called.
    progress_cb:
        Callable that accepts a single float in [0.0, 1.0].
        Call it periodically so the API can report progress to clients.

    Raises
    ------
    NotImplementedError
        Always — until a real implementation replaces this stub.
    """
    raise NotImplementedError(
        "train_profile() is a stub. "
        "Plug in your real fine-tuning code (One-DM / DiffusionPen / etc.)."
    )


def render_pdf(
    input_pdf_path: Path,
    checkpoint_path: Path,
    output_pdf_path: Path,
    progress_cb: ProgressCallback,
) -> None:
    """Render *input_pdf_path* in the writer's style and save to *output_pdf_path*.

    Delegates to :func:`app.ml.render.render_pdf`.  If no trained checkpoint
    is available at *checkpoint_path*, a synthetic handwriting renderer is
    used as a fallback so the pipeline still produces output.

    Parameters
    ----------
    input_pdf_path:
        Path to the uploaded source PDF.
    checkpoint_path:
        Path to the trained model checkpoint produced by ``train_profile``.
    output_pdf_path:
        Where the finished handwritten PDF should be written.
        The parent directory is guaranteed to exist.
    progress_cb:
        Callable that accepts a single float in [0.0, 1.0].

    Raises
    ------
    FileNotFoundError
        If *input_pdf_path* does not exist.
    """
    from app.ml.render import render_pdf as _do_render

    _do_render(input_pdf_path, checkpoint_path, output_pdf_path, progress_cb)
