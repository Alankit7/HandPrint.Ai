"""Structured stdout logging — called once at startup."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    for noisy in ("uvicorn.access", "apscheduler", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
