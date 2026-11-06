from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plainread import ocr
from plainread.api import create_app
from plainread.config import Settings

ROOT = Path(__file__).resolve().parents[1]
EVAL_LETTERS = ROOT / "eval" / "letters"

COURT_LETTER = """LAKEMONT COUNTY SUPERIOR COURT
Small Claims Division
200 Main Street, Lakemont, WS 55501
(312) 555-0142

Date: February 24, 2026

Case No.: SC-2026-004512

SUMMONS — SMALL CLAIMS

You are being sued by Pinecrest Property Management (the plaintiff) for $1,250.00 in unpaid rent.

You must appear at a hearing on Friday, March 20, 2026 at 9:00 a.m. in Courtroom 4B. If you do not appear, the court may enter a default judgment against you.

You must file a written answer with the clerk within twenty (20) days after you are served with this summons.

Please bring the following to your hearing:
- Photo ID
- Any receipts or photos about your case

You have the right to a free interpreter. Call 1-800-555-0177. TTY: 711.

Visit www.lakemontcourts.example/selfhelp or email clerk@lakemontcourts.example.
"""

TODAY = dt.date(2026, 3, 2)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if ocr.ocr_available():
        return
    skip = pytest.mark.skip(reason="Tesseract OCR is not installed")
    for item in items:
        if "ocr" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def court_letter() -> str:
    return COURT_LETTER


@pytest.fixture
def settings() -> Settings:
    s = Settings()
    s.ai = "off"
    return s


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
