"""Settings, read from environment variables (all optional)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _default_ollama_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if not host:
        return "http://127.0.0.1:11434"
    if host.startswith(("http://", "https://")):
        return host.rstrip("/")
    if host.startswith("0.0.0.0"):  # noqa: S104 - a bind address, we only connect to it
        host = "127.0.0.1" + host[len("0.0.0.0") :]  # noqa: S104
    return "http://" + (host if ":" in host else host + ":11434")


@dataclass
class Settings:
    host: str = field(default_factory=lambda: _env("PLAINREAD_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PLAINREAD_PORT", "8765")))
    ai: Literal["auto", "off"] = field(
        default_factory=lambda: "off" if _env("PLAINREAD_AI", "auto").lower() == "off" else "auto"
    )
    ai_backend: Literal["ollama", "openai"] = field(
        default_factory=lambda: (
            "openai" if _env("PLAINREAD_AI_BACKEND", "ollama").lower() == "openai" else "ollama"
        )
    )
    ollama_url: str = field(
        default_factory=lambda: _env("PLAINREAD_OLLAMA_URL", _default_ollama_url())
    )
    openai_url: str = field(
        default_factory=lambda: _env("PLAINREAD_AI_URL", "http://127.0.0.1:8080/v1")
    )
    model: str = field(default_factory=lambda: _env("PLAINREAD_MODEL", "gemma3:4b"))
    ai_timeout: float = field(default_factory=lambda: float(_env("PLAINREAD_AI_TIMEOUT", "300")))
    allow_remote_ai: bool = field(default_factory=lambda: _flag("PLAINREAD_ALLOW_REMOTE_AI"))
    ocr_lang: str = field(default_factory=lambda: _env("PLAINREAD_OCR_LANG", "eng"))
    date_order: Literal["MDY", "DMY"] = field(
        default_factory=lambda: (
            "DMY" if _env("PLAINREAD_DATE_ORDER", "MDY").upper() == "DMY" else "MDY"
        )
    )
    max_upload_mb: int = field(default_factory=lambda: int(_env("PLAINREAD_MAX_UPLOAD_MB", "25")))
    max_files: int = field(default_factory=lambda: int(_env("PLAINREAD_MAX_FILES", "10")))

    @property
    def ai_url(self) -> str:
        return self.ollama_url if self.ai_backend == "ollama" else self.openai_url
