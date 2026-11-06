import datetime as dt
import re
from typing import Any

import pytest

from plainread import i18n

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            out.update(flatten(value, f"{prefix}{key}."))
        return out
    return {prefix[:-1]: node}


CODES = [lang["code"] for lang in i18n.languages()]


def test_twelve_languages_english_first():
    assert CODES[0] == "en"
    assert set(CODES) == {"en", "es", "zh", "vi", "tl", "ko", "ru", "ar", "ht", "fr", "pt", "hi"}


@pytest.mark.parametrize("code", CODES)
def test_locale_matches_english(code):
    english = flatten(i18n.load("en"))
    other = flatten(i18n.load(code))
    assert set(other) == set(english)
    for key, value in english.items():
        if key.startswith("_meta"):
            continue
        if isinstance(value, str):
            assert set(PLACEHOLDER.findall(other[key])) == set(PLACEHOLDER.findall(value)), key
    assert len(other["months"]) == 12
    assert len(other["weekdays"]) == 7


def test_resolve_aliases():
    assert i18n.resolve("es-MX") == "es"
    assert i18n.resolve("zh-Hans") == "zh"
    assert i18n.resolve("fil") == "tl"
    assert i18n.resolve("xx") == "en"
    assert i18n.resolve(None) == "en"


def test_translate_and_plural():
    assert i18n.t("en", "ui.at_time", time="9:00 AM") == "at 9:00 AM"
    assert i18n.tn("en", "relative.in_days", 1) == "in 1 day"
    assert i18n.tn("en", "relative.in_days", 5) == "in 5 days"
    assert i18n.t("en", "no.such.key") == "no.such.key"


def test_format_date():
    day = dt.date(2026, 11, 6)
    assert i18n.format_date(day, "en") == "Friday, November 6, 2026"
    assert i18n.format_date(day, "es") == "viernes, 6 de noviembre de 2026"
    assert "2026" in i18n.format_date(day, "zh")


def test_relative_day():
    assert i18n.relative_day(0, "en") == "today"
    assert i18n.relative_day(1, "en") == "tomorrow"
    assert i18n.relative_day(-3, "en") == "3 days ago"
