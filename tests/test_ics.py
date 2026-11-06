import datetime as dt

from plainread.ics import _escape, _fold, build_calendar
from plainread.models import ImportantDate, Quote


def make_date(time: str | None = None) -> ImportantDate:
    return ImportantDate(
        date=dt.date(2026, 3, 20),
        time=time,
        kind="hearing",
        label="Court date",
        description="Go to court, Room 4B; bring ID.",
        date_text="Friday, March 20, 2026",
        quote=Quote(text="You must appear at a hearing on March 20, 2026.", start=0, end=47),
    )


def test_all_day_event_with_reminders():
    ics = build_calendar(
        [make_date()], sender="Lakemont Court", now=dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
    )
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20260320" in ics
    assert "DTEND;VALUE=DATE:20260321" in ics
    assert "SUMMARY:Court date – Lakemont Court" in ics
    assert ics.count("BEGIN:VALARM") == 2
    assert "DTSTAMP:20260301T000000Z" in ics
    assert ics.endswith("END:VCALENDAR\r\n")


def test_timed_event():
    ics = build_calendar([make_date("9:00 AM")])
    assert "DTSTART:20260320T090000" in ics
    assert "DTEND:20260320T100000" in ics


def test_escaping_and_folding():
    assert _escape("a,b;c\nd") == "a\\,b\\;c\\nd"
    long_line = "DESCRIPTION:" + "é" * 100
    folded = _fold(long_line)
    for part in folded.split("\r\n "):
        assert len(part.encode("utf-8")) <= 75
    assert folded.replace("\r\n ", "") == long_line
