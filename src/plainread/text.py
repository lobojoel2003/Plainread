"""Text clean-up and sentence splitting with exact character offsets.

Letters mix letterhead lines, ``Label: value`` fields, bullet lists and wrapped
paragraphs. :func:`segment` turns a letter into a list of :class:`Segment` s —
sentences, list items or single lines — each pointing back to its exact
position in the text, so every quote can be highlighted in the original.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ABBREVIATIONS = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "st",
    "no",
    "nos",
    "jr",
    "sr",
    "inc",
    "ltd",
    "co",
    "corp",
    "ave",
    "blvd",
    "rd",
    "ste",
    "apt",
    "dept",
    "fl",
    "vs",
    "v",
    "etc",
    "e.g",
    "i.e",
    "eg",
    "ie",
    "u.s",
    "a.m",
    "p.m",
    "am",
    "pm",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
    "mon",
    "tue",
    "tues",
    "wed",
    "thu",
    "thur",
    "thurs",
    "fri",
    "sat",
    "sun",
    "approx",
    "est",
    "ext",
    "tel",
    "op",
    "rev",
    "ref",
    "acct",
    "attn",
    "pg",
    "pp",
    "sec",
    "secs",
    "art",
    "para",
    "cf",
    "al",
    "gen",
    "gov",
    "hon",
    "esq",
    "ph",
    "md",
    "rn",
    "llc",
    "lp",
    "n.a",
    "p.o",
    "po",
    "bldg",
    "rm",
    "ct",
    "hwy",
    "mt",
    "ft",
    "sq",
}

_BULLET = re.compile(r"^\s*(?:[-*•●▪–‣◦>]|\(?\d{1,2}[.)]|\(?[a-hA-H][.)])\s+")
_LABEL_LINE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 #/&().'\-]{0,40}:\s*\S")
_SENTENCE_END = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s|$)")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Segment:
    """A sentence, list item or line of the letter."""

    start: int
    end: int
    text: str
    block: int
    is_line: bool  # True for header/label/address lines that were not joined

    @property
    def clean(self) -> str:
        """The segment with line breaks and repeated spaces collapsed."""
        return collapse(self.text)

    @property
    def words(self) -> int:
        return len(self.clean.split())


def collapse(value: str) -> str:
    return _WS.sub(" ", value).strip()


def normalize(raw: str) -> str:
    """Tidy OCR or pasted text without changing its words.

    The returned string is the reference text: every offset Plainread reports
    points into it.
    """
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    text = text.replace("\t", "    ").replace(" ", " ").replace("​", "")
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    # Join words split across lines by OCR or hyphenation: "deter-\nmination".
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n ")


def _blocks(text: str) -> list[tuple[int, int]]:
    """Paragraph blocks separated by blank lines, as (start, end) offsets."""
    blocks: list[tuple[int, int]] = []
    pos = 0
    for match in re.finditer(r"\n[ \t]*\n", text):
        if match.start() > pos:
            blocks.append((pos, match.start()))
        pos = match.end()
    if pos < len(text):
        blocks.append((pos, len(text)))
    return blocks


def _lines(text: str, start: int, end: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        nl = text.find("\n", pos, end)
        line_end = end if nl == -1 else nl
        if text[pos:line_end].strip():
            out.append((pos, line_end))
        pos = line_end + 1
    return out


def _is_heading(line: str) -> bool:
    """An ALL-CAPS heading line such as "WHAT YOU MUST DO"."""
    stripped = line.strip()
    letters = [c for c in stripped if c.isalpha()]
    return (
        len(letters) >= 4
        and all(c.isupper() for c in letters)
        and len(stripped) <= 70
        and not stripped.endswith((".", ",", ";"))
        and ":" not in stripped[:-1]
    )


def _is_header_like(line: str) -> bool:
    stripped = line.strip()
    label = _LABEL_LINE.match(stripped)
    if label:
        value = stripped[stripped.index(":") + 1 :].strip()
        if len(stripped) < 90 and (len(value) <= 45 or not _SENTENCE_END.search(value)):
            return True
    if len(stripped) <= 45 and not _SENTENCE_END.search(stripped[-2:] if stripped else ""):
        return True
    return stripped.isupper() and len(stripped) < 90


def _is_abbreviation(text: str, dot_pos: int) -> bool:
    """True if the full stop at ``dot_pos`` ends an abbreviation or initial."""
    i = dot_pos
    while i > 0 and (text[i - 1].isalpha() or text[i - 1] == "."):
        i -= 1
    word = text[i:dot_pos].lower().strip(".")
    if not word or (i > 0 and text[i - 1].isdigit()):
        return False
    if word in _ABBREVIATIONS:
        return True
    # Single capital letters ("J. Smith") and dotted acronyms ("U.S.A.").
    return len(word) == 1 or bool(re.fullmatch(r"(?:[a-z]\.)+[a-z]?", word))


def _split_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    seg_start = start
    for match in _SENTENCE_END.finditer(text, start, end):
        dot = match.start()
        if text[dot] == "." and _is_abbreviation(text, dot):
            # "a.m." followed by a capital letter usually does end a sentence.
            nxt = text[match.end() : match.end() + 3].lstrip()
            prev_word = text[max(start, dot - 4) : dot + 1].lower()
            if not (prev_word.endswith(("a.m.", "p.m.")) and nxt[:1].isupper()):
                continue
        # Decimal numbers and versions: "$12.50", "1.5"
        if text[dot] == "." and match.end() < end and text[match.end() : match.end() + 1].isdigit():
            continue
        following = text[match.end() : match.end() + 2].lstrip()
        if following and following[0].islower():
            continue
        spans.append((seg_start, match.end()))
        seg_start = match.end()
    if seg_start < end:
        spans.append((seg_start, end))
    trimmed: list[tuple[int, int]] = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            trimmed.append((s, e))
    return trimmed


def segment(text: str) -> list[Segment]:
    """Split a normalised letter into sentences, list items and header lines."""
    segments: list[Segment] = []
    for block_index, (b_start, b_end) in enumerate(_blocks(text)):
        lines = _lines(text, b_start, b_end)
        if not lines:
            continue
        header_like = sum(_is_header_like(text[s:e]) for s, e in lines)
        if len(lines) == 1 and _is_header_like(text[lines[0][0] : lines[0][1]]):
            # A single short line (title, label field) stays whole...
            s, e = lines[0]
            if _LABEL_LINE.match(text[s:e]) or len(text[s:e].strip()) <= 60:
                segments.append(Segment(s, e, text[s:e], block_index, True))
                continue
        no_sentences = not any(
            text[s:e].rstrip().endswith((".", "!", "?", ":", ";")) for s, e in lines
        )
        if len(lines) > 1 and (
            header_like / len(lines) >= 0.6 or (block_index <= 1 and no_sentences)
        ):
            for s, e in lines:
                segments.append(Segment(s, e, text[s:e], block_index, True))
            continue
        # Flowing paragraph. Split into units at bullets and label lines, then
        # into sentences.
        units: list[list[tuple[int, int]]] = []
        for s, e in lines:
            line = text[s:e]
            previous = text[units[-1][-1][0] : units[-1][-1][1]] if units else ""
            starts_unit = (
                not units
                or bool(_BULLET.match(line))
                or bool(_LABEL_LINE.match(line) and len(line.strip()) < 70)
                or previous.rstrip().endswith(":")
                or _is_heading(previous)
                or _is_heading(line)
            )
            if starts_unit:
                units.append([(s, e)])
            else:
                units[-1].append((s, e))
        for unit in units:
            u_start, u_end = unit[0][0], unit[-1][1]
            if len(unit) == 1 and (
                (_LABEL_LINE.match(text[u_start:u_end]) and len(text[u_start:u_end].strip()) < 70)
                or _is_heading(text[u_start:u_end])
            ):
                segments.append(Segment(u_start, u_end, text[u_start:u_end], block_index, True))
                continue
            for s, e in _split_sentences(text, u_start, u_end):
                segments.append(Segment(s, e, text[s:e], block_index, False))
    return segments


def segment_at(segments: list[Segment], offset: int) -> Segment | None:
    for seg in segments:
        if seg.start <= offset < seg.end:
            return seg
    return None


def strip_bullet(value: str) -> str:
    return _BULLET.sub("", value, count=1)


_VOWEL_GROUPS = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    word = word.lower().strip(".,;:!?\"'()")
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    return max(1, len(_VOWEL_GROUPS.findall(word)))


def reading_grade(segments: list[Segment]) -> float | None:
    """Flesch–Kincaid grade level of the letter's prose sentences."""
    sentences = [s.clean for s in segments if not s.is_line and s.words >= 4]
    if len(sentences) < 2:
        return None
    words = [w for s in sentences for w in s.split() if re.search(r"[A-Za-z]", w)]
    if len(words) < 30:
        return None
    syl = sum(syllables(w) for w in words)
    grade = 0.39 * (len(words) / len(sentences)) + 11.8 * (syl / len(words)) - 15.59
    return round(max(1.0, min(grade, 20.0)), 1)
