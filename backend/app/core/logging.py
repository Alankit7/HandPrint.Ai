"""Structured stdout logging — called once at startup.

Supports two formats selected via the LOG_FORMAT environment variable:
  - ``text``  (default): human-readable ``%(asctime)s [%(levelname)s] %(name)s — %(message)s``
  - ``json``:           one JSON object per line for log aggregators
                        (CloudWatch, Datadog, ELK, Grafana Loki, etc.)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record on a single line."""

    _std_fields = {
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include any extra fields the caller attached via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in self._std_fields and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """Configure root logging.

    Parameters
    ----------
    level:
        Logging level string (``DEBUG``, ``INFO``, ``WARNING``, etc.).
        Defaults to ``LOG_LEVEL`` env var or ``INFO``.
    fmt:
        Output format — ``text`` or ``json``.
        Defaults to ``LOG_FORMAT`` env var or ``text``.
    """
    level = level or os.environ.get("LOG_LEVEL", "INFO")
    fmt = fmt or os.environ.get("LOG_FORMAT", "text")

    handler = logging.StreamHandler(sys.stdout)
    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Quieten noisy third-party loggers
    for noisy in ("uvicorn.access", "apscheduler", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
