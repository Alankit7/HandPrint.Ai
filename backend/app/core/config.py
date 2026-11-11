"""Central settings — every tunable sourced from environment / .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Server ────────────────────────────────────────────────────────────────
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # ── Auth ──────────────────────────────────────────────────────────────────
    api_key: str = Field(..., min_length=8)

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/db/handprint.db"

    # ── Storage ───────────────────────────────────────────────────────────────
    upload_dir: Path = Path("data/uploads")
    sample_dir: Path = Path("data/samples")
    output_dir: Path = Path("data/outputs")

    # ── File-size limits ──────────────────────────────────────────────────────
    max_sample_image_mb: int = Field(10, ge=1)
    max_pdf_mb: int = Field(50, ge=1)

    # ── Sample image constraints ──────────────────────────────────────────────
    min_sample_images: int = Field(15, ge=1)
    max_sample_images: int = Field(30, ge=1)

    # ── Workers ───────────────────────────────────────────────────────────────
    worker_threads: int = Field(2, ge=1)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup_age_hours: int = Field(24, ge=1)
    cleanup_interval_minutes: int = Field(60, ge=1)

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = "*"

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("upload_dir", "sample_dir", "output_dir", mode="before")
    @classmethod
    def _ensure_dir(cls, v: str | Path) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def max_sample_image_bytes(self) -> int:
        return self.max_sample_image_mb * 1024 * 1024

    @property
    def max_pdf_bytes(self) -> int:
        return self.max_pdf_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# Module-level singleton — import everywhere
settings = Settings()
