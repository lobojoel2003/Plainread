"""Find dates, times and "within N days" periods in letter text."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Literal

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty-one": 21,
    "twenty-five": 25,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "seventy-five": 75,
    "eighty": 80,
    "ninety": 90,
    "one hundred twenty": 120,
    "one hundred eighty": 180,
    "a hundred eighty": 180,
}

_MONTH_RE = (
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])\.?"
)
_SP = r"(?:[ \t]+|[ \t]*\n[ \t]*)"  # spaces, or one line break (never a blank line)
_WEEKDAY_RE = (
    r"(?:(?P<weekday>mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?"
    r"|fri(?:day)?|sat(?:urday)?|sun(?:day)?)(?![a-z])\.?,?[ \t]+(?:the[ \t]+)?)?"
)
_DAY_RE = r"(?P<day>[0-3]?\d)(?:st|nd|rd|th)?"
_YEAR_RE = r"(?P<year>(?:19|20)\d{2})"

# "Monday, March 16, 2026" / "Mar. 16 2026" / "March 16th"
_MDY_WORDS = re.compile(
    rf"\b{_WEEKDAY_RE}{_MONTH_RE}{_SP}{_DAY_RE}\b(?:,?{_SP}{_YEAR_RE}\b)?", re.IGNORECASE
)
# "16 March 2026" / "the 3rd of June, 2026" / "Monday 16 March"
_DMY_WORDS = re.compile(
    rf"\b{_WEEKDAY_RE}{_DAY_RE}{_SP}(?:of{_SP})?{_MONTH_RE}(?:,?{_SP}{_YEAR_RE}\b)?", re.IGNORECASE
)
_ISO = re.compile(r"\b(?P<year>(?:19|20)\d{2})-(?P<m>[01]?\d)-(?P<d>[0-3]?\d)\b")
_NUMERIC = re.compile(
    rf"\b{_WEEKDAY_RE}(?P<a>[0-3]?\d)(?P<sep>[/.\-])(?P<b>[0-3]?\d)(?P=sep)(?P<y>(?:19|20)?\d{{2}})\b",
    re.IGNORECASE,
)
_TIME = re.compile(
    r"\b(?P<h>[01]?\d|2[0-3])(?::(?P<m>[0-5]\d))?\s*(?P<ampm>a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])"
    r"|\b(?P<h24>[01]\d|2[0-3]):(?P<m24>[0-5]\d)\b(?!\s*(?:a\.?m|p\.?m))"
    r"|\b(?P<noon>noon|midnight)\b",
    re.IGNORECASE,
)

_NUMWORD = (
    r"(?:a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)"
)
_NUM = (
    rf"(?:(?P<word>{_NUMWORD}(?:[\s-]+{_NUMWORD}){{0,3}})\s*\(\s*(?P<num1>\d{{1,3}})\s*\)"
    rf"|(?P<num2>\d{{1,3}})|(?P<word2>{_NUMWORD}(?:[\s-]+{_NUMWORD}){{0,3}}))"
)
_RELATIVE = re.compile(
    rf"(?P<cue>\bwithin|\bno\s+later\s+than|\bnot\s+later\s+than|\bhave|\bhas|\bin|\bat\s+least)?\s*"
    rf"\b{_NUM}\s+(?P<type>calendar\s+|business\s+|working\s+)?days?\b"
    r"(?P<tail>[^.;]{0,90})",
    re.IGNORECASE,
)
_ANCHOR_LETTER = re.compile(
    r"\b(?:of|from|after|following)\s+(?:the\s+)?(?:date\s+(?:of|on|shown\s+on|printed\s+on|at\s+the\s+top\s+of)\s+this"
    r"|date\s+(?:above|shown\s+above|at\s+the\s+top)|(?:notice|letter|mailing|mail|issue)\s+date"
    r"|date\s+(?:this|the)\s+(?:letter|notice|decision)\s+(?:was|is)\s+(?:mailed|sent|issued|dated)"
    r"|date\s+of\s+(?:mailing|this\s+(?:letter|notice|decision|determination))"
    r"|mailing|this\s+(?:letter|notice|decision|determination))",
    re.IGNORECASE,
)
_ANCHOR_RECEIPT = re.compile(
    r"\b(?:of|from|after|following)\s+(?:the\s+(?:date|day)\s+(?:that\s+|on\s+which\s+)?)?"
    r"(?:you\s+(?:are\s+|were\s+|have\s+been\s+|first\s+)?)?(?:being\s+)?"
    r"(?:receiv\w*|receipt|get|got|served|service\s+of)\b",
    re.IGNORECASE,
)
_OBLIGATION_BEFORE = re.compile(
    r"\b(?:must|should|need to|required|deadline|due)\b[^.;]{0,80}$", re.IGNORECASE
)
_ANCHOR_OTHER = re.compile(
    r"\b(?:before|prior\s+to|after)\s+(?:your|the)\s+(?:appointment|hearing|interview|procedure|visit)",
    re.IGNORECASE,
)

Anchor = Literal["letter", "receipt", "none"]


@dataclass(frozen=True)
class DateMatch:
    start: int
    end: int
    text: str
    month: int
    day: int
    year: int | None
    weekday: int | None

    def resolve(self, reference: dt.date | None) -> tuple[dt.date | None, bool]:
        """Return the date (guessing the year if needed) and whether it was guessed."""
        if self.year is not None:
            try:
                return dt.date(self.year, self.month, self.day), False
            except ValueError:
                return None, False
        if reference is None:
            return None, True
        for year in (reference.year, reference.year + 1):
            try:
                candidate = dt.date(year, self.month, self.day)
            except ValueError:
                continue
            if self.weekday is not None and candidate.weekday() == self.weekday:
                return candidate, True
            if self.weekday is None and candidate >= reference - dt.timedelta(days=14):
                return candidate, True
        try:
            return dt.date(reference.year + 1, self.month, self.day), True
        except ValueError:
            return None, True


@dataclass(frozen=True)
class TimeMatch:
    start: int
    end: int
    text: str
    value: dt.time


@dataclass(frozen=True)
class PeriodMatch:
    start: int
    end: int
    text: str
    days: int
    business: bool
    anchor: Anchor


def _year(value: str) -> int:
    year = int(value)
    return year + 2000 if year < 100 else year


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(s < end and start < e for s, e in spans)


def find_dates(text: str, date_order: Literal["MDY", "DMY"] = "MDY") -> list[DateMatch]:
    """All calendar dates written in the text, in reading order."""
    found: list[DateMatch] = []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match[str], month: int, day: int, year: int | None) -> None:
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return
        if _overlaps(taken, m.start(), m.end()):
            return
        weekday = m.groupdict().get("weekday")
        wd = WEEKDAYS.get(weekday.lower().rstrip(".")) if weekday else None
        found.append(DateMatch(m.start(), m.end(), m.group(0), month, day, year, wd))
        taken.append((m.start(), m.end()))

    for m in _ISO.finditer(text):
        add(m, int(m["m"]), int(m["d"]), int(m["year"]))
    for m in _NUMERIC.finditer(text):
        a, b = int(m["a"]), int(m["b"])
        # A two-digit "year" glued to phone numbers or IDs is not a date.
        before = text[max(0, m.start() - 1) : m.start()]
        after = text[m.end() : m.end() + 1]
        if before in ("-", "/") or after in ("-", "/"):
            continue
        if len(m["y"]) == 2 and m["sep"] == ".":
            continue
        if date_order == "DMY" or (a > 12 >= b):
            day, month = a, b
        else:
            month, day = a, b
        add(m, month, day, _year(m["y"]))
    for pattern in (_MDY_WORDS, _DMY_WORDS):
        for m in pattern.finditer(text):
            month_word = m["month"].lower().rstrip(".")
            # "may" is usually the verb ("you may 15 ...") unless capitalised.
            if month_word == "may" and not m["year"] and not m["month"][0].isupper():
                continue
            if month_word in ("mar", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "jan") and (
                not m["month"][0].isupper()
            ):
                continue
            year = int(m["year"]) if m["year"] else None
            add(m, MONTHS[month_word], int(m["day"]), year)
    found.sort(key=lambda d: d.start)
    return found


def find_times(text: str) -> list[TimeMatch]:
    times: list[TimeMatch] = []
    for m in _TIME.finditer(text):
        if m["noon"]:
            value = dt.time(12, 0) if m["noon"].lower() == "noon" else dt.time(0, 0)
        elif m["h24"]:
            value = dt.time(int(m["h24"]), int(m["m24"]))
        else:
            hour = int(m["h"])
            if hour == 0 or hour > 12:
                continue
            minute = int(m["m"] or 0)
            pm = m["ampm"].lower().startswith("p")
            hour = (hour % 12) + (12 if pm else 0)
            value = dt.time(hour, minute)
        times.append(TimeMatch(m.start(), m.end(), m.group(0), value))
    return times


def format_time(value: dt.time) -> str:
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {suffix}"


def _number(m: re.Match[str]) -> int | None:
    if m["num1"]:
        return int(m["num1"])
    if m["num2"]:
        return int(m["num2"])
    word = (m["word2"] or "").lower().replace(" ", "-")
    return NUMBER_WORDS.get(word) or NUMBER_WORDS.get(word.replace("-", " "))


def find_periods(text: str) -> list[PeriodMatch]:
    """Deadlines given as a period: "within 30 days of the date of this notice"."""
    periods: list[PeriodMatch] = []
    for m in _RELATIVE.finditer(text):
        days = _number(m)
        if not days or days > 400:
            continue
        tail = m["tail"] or ""
        cue = (m["cue"] or "").lower()
        if _ANCHOR_OTHER.match(tail.strip()) or re.match(r"\s*(?:before|prior)", tail, re.I):
            continue
        if not cue and not _OBLIGATION_BEFORE.search(text[max(0, m.start() - 90) : m.start()]):
            continue  # "the first three days of service" is not a deadline
        if re.search(
            r"\b(?:first|last|next|per|each|every|those|these|the)\s*$",
            text[max(0, m.start() - 12) : m.start()],
            re.I,
        ) and cue not in ("within",):
            continue
        stripped_tail = tail.strip()
        if (
            re.match(r"(?:of|after|from|following|before|prior\s+to)\b", stripped_tail, re.I)
            and not _ANCHOR_LETTER.match(stripped_tail)
            and not _ANCHOR_RECEIPT.match(stripped_tail)
        ):
            continue  # counted from another event ("after your coverage ends")
        if _ANCHOR_RECEIPT.match(stripped_tail) and re.match(
            r"\S+\s+(?:\S+\s+){0,3}?(?:your|the)\s+(?:appeal|request|form|application|payment|claim|complaint)",
            stripped_tail,
            re.I,
        ):
            continue  # "within 30 days of receiving your appeal" is the sender's clock
        anchor: Anchor
        if _ANCHOR_LETTER.match(tail.strip()):
            anchor = "letter"
        elif _ANCHOR_RECEIPT.match(tail.strip()):
            anchor = "receipt"
        elif cue in ("within", "no later than", "not later than") or re.sub(r"\s+", " ", cue) in (
            "no later than",
            "not later than",
        ):
            # "within 10 days" without saying from when: we count from the letter.
            if re.match(
                r"\s*(?:of|after|from)\s+(?:your|the)\s+(?:appointment|hearing|move|change)",
                tail,
                re.I,
            ):
                continue
            anchor = "none"
        elif cue in ("have", "has") and re.match(r"\s*(?:from|after|of|to)\b", tail, re.I):
            anchor = (
                "letter"
                if _ANCHOR_LETTER.search(tail)
                else ("receipt" if _ANCHOR_RECEIPT.search(tail) else "none")
            )
        else:
            continue
        # The quote is the period phrase plus its anchor words.
        end = m.end(0) - len(tail)
        stripped = tail.lstrip()
        anchor_m = _ANCHOR_LETTER.match(stripped) or _ANCHOR_RECEIPT.match(stripped)
        if anchor_m:
            end += (len(tail) - len(stripped)) + anchor_m.end()
        start = m.start("cue") if m["cue"] else m.start(0)
        while start < end and text[start].isspace():
            start += 1
        business = bool(m["type"] and m["type"].lower().startswith(("business", "working")))
        periods.append(PeriodMatch(start, end, text[start:end], days, business, anchor))
    return periods


def add_days(start: dt.date, days: int, business: bool = False) -> dt.date:
    if not business:
        return start + dt.timedelta(days=days)
    current = start
    added = 0
    while added < days:
        current += dt.timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


_DAY_ONLY = re.compile(
    r"\b(?:on|by|before|until|after|through|starting)\s+(?:[\w.:]+\s+){0,3}?the\s+(?P<day>[0-3]?\d)(?:st|nd|rd|th)\b"
    r"(?!\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|day|week|month|floor))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DayOnlyMatch:
    start: int
    end: int
    text: str
    day: int

    def resolve(self, reference: dt.date) -> dt.date | None:
        """The next such day of the month on or after ``reference``."""
        year, month = reference.year, reference.month
        for _ in range(3):
            try:
                candidate = dt.date(year, month, self.day)
            except ValueError:
                candidate = None
            if candidate and candidate >= reference:
                return candidate
            month += 1
            if month > 12:
                year, month = year + 1, 1
        return None


def find_day_only(text: str) -> list[DayOnlyMatch]:
    """Dates given only as a day of the month: "on the 15th"."""
    out = []
    for m in _DAY_ONLY.finditer(text):
        day = int(m["day"])
        if 1 <= day <= 31:
            start = m.start("day") - len("the ")
            out.append(DayOnlyMatch(start, m.end(), text[start : m.end()], day))
    return out
