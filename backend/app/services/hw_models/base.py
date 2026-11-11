"""Abstract base class all handwriting generators must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image


class BaseHandwritingModel(ABC):
    """
    A few-shot handwriting style transfer model.

    Subclasses accept a list of reference style images (scanned handwriting
    samples from the target person) at load time and expose a single
    ``render_line`` method that converts a source line image (or plain text)
    into a new image in the target handwriting.
    """

    @abstractmethod
    def load(self, checkpoint: Path, device: str) -> None:
        """Load model weights from *checkpoint* onto *device*."""

    @abstractmethod
    def set_style(self, sample_images: list[Image.Image]) -> None:
        """
        Condition the model on the given few-shot style reference images.
        Call this once per job after loading the user's handwriting samples.
        """

    @abstractmethod
    def render_line(self, source: Image.Image) -> Image.Image:
        """
        Convert a single printed line image *source* into the target
        handwriting style.  Returns a new PIL Image of the same height.
        """

    def render_lines(
        self,
        sources: list[Image.Image],
        progress_callback: "ProgressCallback | None" = None,
    ) -> list[Image.Image]:
        """
        Convenience method: render a batch of lines.
        Reports progress via *progress_callback(done, total)* if supplied.
        """
        results: list[Image.Image] = []
        total = len(sources)
        for i, src in enumerate(sources):
            results.append(self.render_line(src))
            if progress_callback:
                progress_callback(i + 1, total)
        return results


from typing import Callable
ProgressCallback = Callable[[int, int], None]
