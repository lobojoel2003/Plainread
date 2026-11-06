"""``python -m plainread`` (and the packaged desktop app) entry point."""

import sys

from plainread.cli import main

if __name__ == "__main__":
    sys.exit(main())
