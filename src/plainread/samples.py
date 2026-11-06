"""Fictional sample letters bundled for demos and the "Try a sample" button.

Sample dates are written as placeholders and filled in relative to today, so
the demo always shows upcoming deadlines:

* ``{{d:+14}}`` -> "March 16, 2026"            (14 days from today)
* ``{{w:+14}}`` -> "Monday, March 16, 2026"    (moved to a weekday)
* ``{{n:-3}}``  -> "03/02/2026"
"""

from __future__ import annotations

import datetime as dt
import json
import re
from importlib import resources
from typing import Any

_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_PLACEHOLDER = re.compile(r"\{\{([dwn]):([+-]\d+)\}\}")


def _folder() -> Any:
    return resources.files("plainread") / "sample_letters"


def _weekday(value: dt.date) -> dt.date:
    while value.weekday() >= 5:
        value += dt.timedelta(days=1)
    return value


def fill_dates(text: str, today: dt.date) -> str:
    def repl(m: re.Match[str]) -> str:
        style, offset = m.group(1), int(m.group(2))
        value = today + dt.timedelta(days=offset)
        if style == "n":
            return f"{value:%m/%d/%Y}"
        if style == "w":
            value = _weekday(value)
            return f"{_DAYS[value.weekday()]}, {_MONTHS[value.month - 1]} {value.day}, {value.year}"
        return f"{_MONTHS[value.month - 1]} {value.day}, {value.year}"

    return _PLACEHOLDER.sub(repl, text)


def list_samples() -> list[dict[str, str]]:
    data: list[dict[str, str]] = json.loads((_folder() / "index.json").read_text("utf-8"))
    return data


def get_sample(sample_id: str, today: dt.date | None = None) -> dict[str, str]:
    for entry in list_samples():
        if entry["id"] == sample_id:
            text = (_folder() / f"{sample_id}.txt").read_text("utf-8")
            return {**entry, "text": fill_dates(text, today or dt.date.today())}
    raise KeyError(sample_id)
