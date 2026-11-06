#!/usr/bin/env python3
"""Bump the version and roll the "Unreleased" changelog section into a release.

    python scripts/bump_version.py patch      # 1.0.0 -> 1.0.1
    python scripts/bump_version.py minor      # 1.0.0 -> 1.1.0
    python scripts/bump_version.py 2.0.0      # explicit

Then commit, tag and push:

    git commit -am "Release v1.0.1" && git tag -a v1.0.1 -m "Plainread 1.0.1" && git push --follow-tags
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "plainread" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO = "https://github.com/lobojoel2003/Plainread"


def current() -> str:
    match = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"', INIT.read_text("utf-8"), re.M)
    if not match:
        sys.exit("Could not read the current version")
    return ".".join(match.groups())


def bumped(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", part):
        sys.exit(f"Not a version or major/minor/patch: {part}")
    return part


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    old = current()
    new = bumped(old, sys.argv[1])
    INIT.write_text(
        re.sub(r'__version__ = "[^"]+"', f'__version__ = "{new}"', INIT.read_text("utf-8")), "utf-8"
    )
    log = CHANGELOG.read_text("utf-8")
    today = dt.date.today().isoformat()
    if "## [Unreleased]" not in log:
        sys.exit("CHANGELOG.md needs an '## [Unreleased]' section")
    log = log.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{new}] - {today}", 1)
    log = re.sub(
        r"^\[Unreleased\]: .*$",
        f"[Unreleased]: {REPO}/compare/v{new}...HEAD\n[{new}]: {REPO}/compare/v{old}...v{new}",
        log,
        count=1,
        flags=re.M,
    )
    CHANGELOG.write_text(log, "utf-8")
    print(f"Bumped {old} -> {new}. Review CHANGELOG.md, then commit and tag v{new}.")


if __name__ == "__main__":
    main()
