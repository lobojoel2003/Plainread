"""Check that quotes really come from the letter.

Rules-engine quotes are exact by construction. AI-written quotes are checked
here: a quote is accepted only if it can be found in the letter, allowing for
differences in spacing, letter case, typographic quotes and small OCR slips.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from plainread.models import Explanation, Quote

_TRANSLATE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
        " ": " ",
    }
)


def _normalize_with_map(value: str) -> tuple[str, list[int]]:
    """Lower-case, unify punctuation and collapse whitespace, remembering offsets."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(value.translate(_TRANSLATE)):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            index.append(i)
            prev_space = True
            continue
        out.append(ch.lower())
        index.append(i)
        prev_space = False
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def _trim_quote(quote: str) -> str:
    quote = quote.strip().strip("\"'“”‘’")
    quote = re.sub(r"^(?:\.\.\.|…)\s*|\s*(?:\.\.\.|…)$", "", quote)
    return quote.strip()


def locate(text: str, quote: str, min_ratio: float = 0.9) -> tuple[int, int] | None:
    """Find ``quote`` in ``text``. Returns (start, end) offsets or None."""
    quote = _trim_quote(quote)
    if len(quote) < 4:
        return None
    exact = text.find(quote)
    if exact != -1:
        return exact, exact + len(quote)
    norm_text, index = _normalize_with_map(text)
    norm_quote, _ = _normalize_with_map(quote)
    if not norm_quote:
        return None
    pos = norm_text.find(norm_quote)
    if pos != -1:
        return index[pos], index[pos + len(norm_quote) - 1] + 1
    # Ignore trailing punctuation differences.
    stripped = norm_quote.rstrip(".,;:!? ")
    if len(stripped) >= 12:
        pos = norm_text.find(stripped)
        if pos != -1:
            return index[pos], index[pos + len(stripped) - 1] + 1
    if len(norm_quote) < 20:
        return None
    # Fuzzy: anchor on the longest common block, then compare a window.
    matcher = SequenceMatcher(None, norm_text, norm_quote, autojunk=False)
    block = matcher.find_longest_match(0, len(norm_text), 0, len(norm_quote))
    if block.size < 8:
        return None
    start_guess = max(0, block.a - block.b)
    best: tuple[float, int, int] = (0.0, 0, 0)
    for delta in range(-6, 7, 2):
        start = max(0, start_guess + delta)
        for size_delta in (-4, 0, 4):
            end = min(len(norm_text), start + len(norm_quote) + size_delta)
            ratio = SequenceMatcher(None, norm_text[start:end], norm_quote, autojunk=False).ratio()
            if ratio > best[0]:
                best = (ratio, start, end)
    ratio, start, end = best
    if ratio < min_ratio or end <= start:
        return None
    return index[start], index[end - 1] + 1


def make_quote(text: str, start: int, end: int) -> Quote:
    return Quote(text=text[start:end], start=start, end=end)


def quote_is_valid(text: str, quote: Quote) -> bool:
    return 0 <= quote.start < quote.end <= len(text) and text[quote.start : quote.end] == quote.text


def grounding_rate(explanation: Explanation) -> float:
    """Share of quotes that are exact substrings of the letter (1.0 = all)."""
    quotes = explanation.all_quotes()
    if not quotes:
        return 1.0
    good = sum(quote_is_valid(explanation.source_text, q) for q in quotes)
    return good / len(quotes)
