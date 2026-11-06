#!/usr/bin/env python3
"""Print the CHANGELOG section for a version, or check a release tag.

python scripts/release_notes.py 1.0.0          # print notes for 1.0.0
python scripts/release_notes.py --check v1.0.0 # tag must match package version + changelog
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
INIT = ROOT / "src" / "plainread" / "__init__.py"
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def package_version() -> str:
    match = re.search(r'^__version__ = "([^"]+)"', INIT.read_text("utf-8"), re.M)
    if not match:
        sys.exit("Could not find __version__ in src/plainread/__init__.py")
    return match.group(1)


def notes_for(version: str) -> str:
    text = CHANGELOG.read_text("utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", re.M | re.S
    )
    match = pattern.search(text)
    if not match:
        sys.exit(f"CHANGELOG.md has no section for [{version}]")
    return match.group(1).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version", nargs="?", help="version to print notes for (default: package version)"
    )
    parser.add_argument(
        "--check", metavar="TAG", help="fail unless TAG is v<package version> with notes"
    )
    args = parser.parse_args()
    if args.check:
        tag = args.check.removeprefix("refs/tags/")
        version = package_version()
        if not SEMVER.match(version):
            sys.exit(f"Package version {version!r} is not semantic versioning (MAJOR.MINOR.PATCH)")
        if tag != f"v{version}":
            sys.exit(
                f"Tag {tag!r} does not match package version {version!r} (expected v{version})"
            )
        notes_for(version)
        print(f"OK: tag {tag} matches version {version} and CHANGELOG.md has release notes")
        return
    print(notes_for(args.version or package_version()))


if __name__ == "__main__":
    main()
