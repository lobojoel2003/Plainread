"""Calendar files (iCalendar / .ics) for the important dates in a letter."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Iterable

from plainread import __version__
from plainread.models import ImportantDate


def _escape(value: str) -> str:
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return re.sub(r"\r?\n", "\\\\n", value)


def _fold(line: str) -> str:
    """Fold long lines at 75 octets as RFC 5545 requires."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: list[str] = []
    current = b""
    for ch in line:
        encoded = ch.encode("utf-8")
        limit = 75 if not parts else 74
        if len(current) + len(encoded) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _parse_time(value: str | None) -> dt.time | None:
    if not value:
        return None
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", value.strip(), re.I)
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    return dt.time(hour, int(m.group(2)))


def build_calendar(
    dates: Iterable[ImportantDate], sender: str | None = None, now: dt.datetime | None = None
) -> str:
    """Return an .ics file with one event (and two reminders) per date."""
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//Plainread//Plainread {__version__}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for item in dates:
        title = item.label + (f" – {sender}" if sender else "")
        quote = re.sub(r"\s+", " ", item.quote.text).strip()
        description = item.description or quote
        if quote and quote != description:
            description += f'\n\nThe letter says: "{quote}"'
        if item.note:
            description += f"\n\n{item.note}"
        uid_source = f"{item.date}|{item.kind}|{quote}".encode()
        uid = hashlib.sha256(uid_source).hexdigest()[:24] + "@plainread"
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}"]
        start_time = _parse_time(item.time)
        if start_time:
            start = dt.datetime.combine(item.date, start_time)
            end = start + dt.timedelta(hours=1)
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}"]
        else:
            nxt = item.date + dt.timedelta(days=1)
            lines += [f"DTSTART;VALUE=DATE:{item.date:%Y%m%d}", f"DTEND;VALUE=DATE:{nxt:%Y%m%d}"]
        lines += [
            f"SUMMARY:{_escape(title)}",
            f"DESCRIPTION:{_escape(description)}",
            "TRANSP:TRANSPARENT",
        ]
        for trigger in ("-P3D", "-P1D"):
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(title)}",
                f"TRIGGER:{trigger}",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
