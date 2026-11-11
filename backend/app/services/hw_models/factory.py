"""Model factory + module-level singleton.

The model is loaded once at startup and reused across all requests.
Call ``get_model()`` from route handlers.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.services.hw_models.base import BaseHandwritingModel

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_model() -> BaseHandwritingModel:
    """Return the loaded (but not yet style-conditioned) handwriting model."""
    if settings.hw_model == "onedm":
        from app.services.hw_models.onedm import OneDMModel
        model: BaseHandwritingModel = OneDMModel(
            img_height=settings.img_height,
            few_shot_k=settings.few_shot_samples,
        )
    else:
        from app.services.hw_models.diffusionpen import DiffusionPenModel
        model = DiffusionPenModel(
            img_height=settings.img_height,
            few_shot_k=settings.few_shot_samples,
        )

    model.load(settings.active_checkpoint, settings.device)
    logger.info("Handwriting model '%s' loaded", settings.hw_model)
    return model
