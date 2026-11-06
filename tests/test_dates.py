import datetime as dt

import pytest

from plainread import dates as d


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("March 15, 2026", dt.date(2026, 3, 15)),
        ("Mar. 15, 2026", dt.date(2026, 3, 15)),
        ("Sept 3 2026", dt.date(2026, 9, 3)),
        ("15 March 2026", dt.date(2026, 3, 15)),
        ("the 3rd of June, 2026", dt.date(2026, 6, 3)),
        ("Monday, March 16, 2026", dt.date(2026, 3, 16)),
        ("03/15/2026", dt.date(2026, 3, 15)),
        ("3/5/26", dt.date(2026, 3, 5)),
        ("2026-03-15", dt.date(2026, 3, 15)),
        ("25/12/2026", dt.date(2026, 12, 25)),  # day > 12 means day first
    ],
)
def test_find_dates_formats(text, expected):
    found = d.find_dates(f"Due on {text}.")
    assert len(found) == 1
    value, guessed = found[0].resolve(None)
    assert value == expected
    assert guessed is False


def test_dmy_order_option():
    (match,) = d.find_dates("04/05/2026", date_order="DMY")
    assert match.resolve(None)[0] == dt.date(2026, 5, 4)


def test_not_dates():
    text = "Case SC-2026-004512. Call 555-0142 or (312) 555-0142. You may 15 items. Page 1 of 2."
    assert d.find_dates(text) == []


def test_year_is_guessed_from_letter_date():
    (match,) = d.find_dates("Return it by June 3.")
    value, guessed = match.resolve(dt.date(2026, 5, 20))
    assert value == dt.date(2026, 6, 3)
    assert guessed is True


def test_year_rolls_over_for_january_deadline_in_december_letter():
    (match,) = d.find_dates("Pay by January 5.")
    assert match.resolve(dt.date(2026, 12, 10))[0] == dt.date(2027, 1, 5)


def test_weekday_helps_pick_the_year():
    (match,) = d.find_dates("Come in on Monday, June 8.")
    assert match.resolve(dt.date(2026, 5, 1))[0] == dt.date(2026, 6, 8)


def test_times():
    times = [t.value for t in d.find_times("at 9:00 a.m., 2 PM, 14:30, noon")]
    assert times == [dt.time(9, 0), dt.time(14, 0), dt.time(14, 30), dt.time(12, 0)]
    assert d.format_time(dt.time(14, 5)) == "2:05 PM"


@pytest.mark.parametrize(
    ("text", "days", "business", "anchor"),
    [
        ("You have thirty (30) days from the date of this notice to appeal.", 30, False, "letter"),
        ("Appeal within 60 days after you receive this letter.", 60, False, "receipt"),
        ("File an answer within twenty (20) days after you are served.", 20, False, "receipt"),
        ("Return the form within 10 business days of the date of this letter.", 10, True, "letter"),
        ("You must reply within 14 days.", 14, False, "none"),
        ("Request a review no later than 90 days after the mailing date.", 90, False, "letter"),
    ],
)
def test_periods(text, days, business, anchor):
    (period,) = d.find_periods(text)
    assert (period.days, period.business, period.anchor) == (days, business, anchor)


@pytest.mark.parametrize(
    "text",
    [
        "Please allow 7-10 business days for processing.",
        "Jurors are paid $15 for the first three days of service.",
        "Cancel at least 2 days before your appointment.",
        "You were paid for 14 days in March.",
    ],
)
def test_not_periods(text):
    assert d.find_periods(text) == []


def test_add_business_days_skips_weekends():
    friday = dt.date(2026, 3, 6)
    assert d.add_days(friday, 1, business=True) == dt.date(2026, 3, 9)
    assert d.add_days(friday, 10, business=True) == dt.date(2026, 3, 20)
    assert d.add_days(friday, 10) == dt.date(2026, 3, 16)
