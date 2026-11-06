"""Version and build information.

The version number lives in ``plainread/__init__.py`` (single source of truth).
CI writes ``plainread/_build.py`` with the build number, commit and build date
(see ``scripts/stamp_build.py``). Local checkouts fall back to "dev".
"""

from __future__ import annotations

import os
from typing import TypedDict

from plainread import __version__

try:  # pragma: no cover - only present in CI-built packages
    from plainread._build import BUILD_DATE, BUILD_NUMBER, COMMIT
except ImportError:
    BUILD_NUMBER = os.environ.get("PLAINREAD_BUILD_NUMBER", "dev")
    COMMIT = os.environ.get("PLAINREAD_COMMIT", "unknown")
    BUILD_DATE = os.environ.get("PLAINREAD_BUILD_DATE", "")


class BuildInfo(TypedDict):
    version: str
    build: str
    commit: str
    build_date: str


def build_info() -> BuildInfo:
    return {
        "version": __version__,
        "build": str(BUILD_NUMBER),
        "commit": str(COMMIT)[:12],
        "build_date": str(BUILD_DATE),
    }


def version_string() -> str:
    """Human-readable version, e.g. ``1.0.0 (build 42, commit 1a2b3c4)``."""
    info = build_info()
    if info["build"] == "dev":
        return f"{info['version']} (development build)"
    return f"{info['version']} (build {info['build']}, commit {info['commit'][:7]})"
