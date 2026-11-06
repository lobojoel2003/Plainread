"""Translations for labels, headings and summary sentences.

Locale files live in ``plainread/locales/<code>.json``. The web app loads the
same files through ``/api/i18n/<code>``, so there is one source of truth.
"""

from __future__ import annotations

import datetime as dt
import json
from functools import cache
from importlib import resources
from typing import Any

DEFAULT_LANGUAGE = "en"

_ALIASES = {
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-sg": "zh",
    "fil": "tl",
    "pt-br": "pt",
    "pt-pt": "pt",
    "es-us": "es",
    "es-mx": "es",
    "es-419": "es",
    "fr-ca": "fr",
    "ar-sa": "ar",
    "hi-in": "hi",
}


@cache
def _locale_files() -> dict[str, str]:
    folder = resources.files("plainread") / "locales"
    return {
        entry.name[:-5]: entry.read_text(encoding="utf-8")
        for entry in folder.iterdir()
        if entry.name.endswith(".json")
    }


@cache
def load(code: str) -> dict[str, Any]:
    raw = _locale_files().get(code)
    if raw is None:
        raise KeyError(code)
    data: dict[str, Any] = json.loads(raw)
    return data


def resolve(code: str | None) -> str:
    """Map a language tag such as ``es-MX`` to a supported locale code."""
    if not code:
        return DEFAULT_LANGUAGE
    key = code.strip().lower().replace("_", "-")
    available = _locale_files()
    if key in available:
        return key
    if key in _ALIASES and _ALIASES[key] in available:
        return _ALIASES[key]
    base = key.split("-")[0]
    return base if base in available else DEFAULT_LANGUAGE


def languages() -> list[dict[str, str]]:
    """Supported languages, English first, then by English name."""
    out = []
    for code in _locale_files():
        meta = load(code)["_meta"]
        out.append(
            {
                "code": code,
                "name": meta["name"],
                "native_name": meta["native_name"],
                "dir": meta.get("dir", "ltr"),
                "speech": meta.get("speech", code),
            }
        )
    out.sort(key=lambda m: (m["code"] != DEFAULT_LANGUAGE, m["name"]))
    return out


def _lookup(data: dict[str, Any], key: str) -> Any:
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def t(lang: str, key: str, **values: object) -> str:
    """Translate ``key`` (dotted path) into ``lang``, falling back to English."""
    text = _lookup(load(resolve(lang)), key)
    if not isinstance(text, str):
        text = _lookup(load(DEFAULT_LANGUAGE), key)
    if not isinstance(text, str):
        return key
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def tn(lang: str, key: str, count: int, **values: object) -> str:
    """Translate a counted phrase using its ``_one`` / ``_other`` forms."""
    suffix = "_one" if count == 1 else "_other"
    return t(lang, key + suffix, count=count, **values)


def direction(lang: str) -> str:
    return str(load(resolve(lang))["_meta"].get("dir", "ltr"))


def language_name(lang: str) -> str:
    return str(load(resolve(lang))["_meta"]["name"])


def format_date(value: dt.date, lang: str) -> str:
    data = load(resolve(lang))
    months = data.get("months") or load(DEFAULT_LANGUAGE)["months"]
    weekdays = data.get("weekdays") or load(DEFAULT_LANGUAGE)["weekdays"]
    pattern = data.get("date_format") or "{weekday}, {month} {day}, {year}"
    return str(pattern).format(
        weekday=weekdays[value.weekday()],
        month=months[value.month - 1],
        day=value.day,
        year=value.year,
    )


def relative_day(days: int, lang: str) -> str:
    if days == 0:
        return t(lang, "relative.today")
    if days == 1:
        return t(lang, "relative.tomorrow")
    if days == -1:
        return t(lang, "relative.yesterday")
    if days > 0:
        return tn(lang, "relative.in_days", days)
    return tn(lang, "relative.days_ago", -days)
