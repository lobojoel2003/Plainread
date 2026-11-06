"""Entry point for the standalone desktop build (PyInstaller).

Double-clicking the app starts the local web server and opens the browser.
"""

import multiprocessing
import sys

from plainread.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
