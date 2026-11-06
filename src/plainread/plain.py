"""Rewrite official sentences in plainer English without changing their meaning.

This is deliberately conservative: it only swaps phrases whose plain version
means the same thing in any context. The original words are always shown next
to the plain version, so nothing is lost.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from plainread.text import collapse, strip_bullet

# Phrases that add nothing for the reader. Removed at the start of a sentence.
_FILLER_STARTS = [
    r"(?:re|subject|regarding)\s*:\s*",
    r"please be (?:advised|informed|aware) that,?\s*",
    r"be advised that,?\s*",
    r"please note that,?\s*",
    r"please note:?\s*",
    r"you are hereby (?:notified|informed|advised) that,?\s*",
    r"notice is hereby given that,?\s*",
    r"this (?:letter|notice) is to (?:inform|notify|advise) you that,?\s*",
    r"we are writing to (?:inform|notify|advise|let) you (?:know )?that,?\s*",
    r"we are writing to (?:inform|notify|advise|tell) you,?\s*",
    r"this is to (?:inform|notify|advise) you that,?\s*",
    r"we (?:would like to|wish to|want to) (?:inform|notify|advise|let) you (?:know )?that,?\s*",
    r"important:\s*",
    r"attention:\s*",
]

# (pattern, replacement). Order matters: longer phrases first.
_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bin accordance with\b", "under"),
    (r"\bpursuant to\b", "under"),
    (r"\bin compliance with\b", "following"),
    (r"\bin the event that\b", "if"),
    (r"\bin the event of\b", "if there is"),
    (r"\bin order to\b", "to"),
    (r"\bfor the purpose of\b", "to"),
    (r"\bwith (?:regard|respect) to\b", "about"),
    (r"\bin regard to\b", "about"),
    (r"\bin reference to\b", "about"),
    (r"\bat this point in time\b", "now"),
    (r"\bat this time\b", "now"),
    (r"\bprior to\b", "before"),
    (r"\bsubsequent to\b", "after"),
    (r"\bin lieu of\b", "instead of"),
    (r"\bdue to the fact that\b", "because"),
    (r"\bon the grounds that\b", "because"),
    (r"\bin the amount of\b", "of"),
    (r"\bat the earliest possible date\b", "as soon as you can"),
    (r"\bas soon as possible\b", "soon"),
    (r"\bis required to\b", "must"),
    (r"\bare required to\b", "must"),
    (r"\bit is necessary that you\b", "you must"),
    (r"\byou are obligated to\b", "you must"),
    (r"\bshall\b", "must"),
    (r"\bwill result in\b", "will lead to"),
    (r"\bmay result in\b", "may lead to"),
    (r"\bcould result in\b", "could lead to"),
    (r"\bcommence(?:s)?\b", "start"),
    (r"\bcommencement\b", "start"),
    (r"\bterminated\b", "ended"),
    (r"\bterminate\b", "end"),
    (r"\btermination of\b", "ending of"),
    (r"\bdiscontinued\b", "stopped"),
    (r"\bdiscontinue\b", "stop"),
    (r"\bremit\b", "send"),
    (r"\bremittance\b", "payment"),
    (r"\bfurnish\b", "give"),
    (r"\bobtain\b", "get"),
    (r"\butilize\b", "use"),
    (r"\bsufficient\b", "enough"),
    (r"\binsufficient\b", "not enough"),
    (r"\bapproximately\b", "about"),
    (r"\bassistance\b", "help"),
    (r"\bassist\b", "help"),
    (r"\bendeavor\b", "try"),
    (r"\bexpedite\b", "speed up"),
    (r"\binquiries\b", "questions"),
    (r"\binquiry\b", "question"),
    (r"\bherein\b", "here"),
    (r"\bhereby\s+", ""),
    (r"\baforementioned\b", "this"),
    (r"\bthe undersigned\b", "us"),
    (r"\bindicated\b", "shown"),
    (r"\bmonies\b", "money"),
    (r"\bfunds\b", "money"),
    (r"\bpurchase\b", "buy"),
    (r"\breside\b", "live"),
    (r"\bresidence\b", "home"),
    (r"\bdwelling unit\b", "home"),
    (r"\bpremises\b", "home or property"),
    (r"\bvacate\b", "move out of"),
    (r"\bdeemed\b", "treated as"),
    (r"\bat no cost to you\b", "for free"),
    (r"\bfree of charge\b", "for free"),
    (r"\bupon receipt of\b", "when you get"),
    (r"\bupon\b", "on"),
    (r"\bmandatory\b", "required"),
]

_DUPLICATE_NUMBER = re.compile(r"\b(?:[a-z]+(?:[ -][a-z]+){0,2})\s*\((\d+)\)", re.IGNORECASE)
_NUMBER_WORD = re.compile(
    r"^(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|one hundred|twenty-one|forty-five|seventy-five|one hundred eighty|one hundred twenty)\b",
    re.IGNORECASE,
)


def _match_case(replacement: str, original: str) -> str:
    if original[:1].isupper() and replacement:
        return replacement[0].upper() + replacement[1:]
    return replacement


def _replacer(replacement: str) -> Callable[[re.Match[str]], str]:
    def repl(m: re.Match[str]) -> str:
        return _match_case(replacement, m.group(0))

    return repl


def _dedupe_numbers(text: str) -> str:
    """ "thirty (30) days" -> "30 days"."""

    def repl(m: re.Match[str]) -> str:
        words = m.group(0)[: m.group(0).index("(")].strip()
        # Only drop number words; keep "Form (2)" etc.
        tail = words.split()
        for size in (3, 2, 1):
            phrase = " ".join(tail[-size:])
            if len(tail) >= size and _NUMBER_WORD.fullmatch(phrase):
                kept = " ".join(tail[:-size])
                return (kept + " " if kept else "") + m.group(1)
        return m.group(0)

    return _DUPLICATE_NUMBER.sub(repl, text)


def simplify(sentence: str) -> str:
    """Return a plainer version of one sentence from a letter."""
    text = collapse(strip_bullet(sentence))
    for pattern in _FILLER_STARTS:
        new = re.sub(r"^" + pattern, "", text, flags=re.IGNORECASE)
        if new != text:
            text = new[:1].upper() + new[1:]
    for pattern, replacement in _REPLACEMENTS:
        text = re.sub(pattern, _replacer(replacement), text, flags=re.IGNORECASE)
    text = _dedupe_numbers(text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text
