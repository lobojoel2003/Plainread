import datetime as dt

from plainread.extract import extract, table_fields
from plainread.text import normalize, segment

from .conftest import COURT_LETTER, TODAY


def run(text: str, today: dt.date = TODAY):
    clean = normalize(text)
    return clean, extract(clean, segment(clean), today)


def test_court_letter_dates_and_kinds():
    _, f = run(COURT_LETTER)
    assert f.letter_date == dt.date(2026, 2, 24)
    found = {(x.date, x.kind) for x in f.dates}
    assert (dt.date(2026, 3, 20), "hearing") in found
    # "within twenty (20) days after you are served" -> counted from the letter date
    answer = next(x for x in f.dates if x.calculated)
    assert answer.date == dt.date(2026, 3, 16)
    assert answer.note_key == "calc_from_receipt"
    hearing = next(x for x in f.dates if x.kind == "hearing")
    assert hearing.time == dt.time(9, 0)


def test_past_dates_and_birthdays_are_not_deadlines():
    text = (
        "Notice Date: May 4, 2026\n\n"
        "Date of Birth: 06/01/1980\n\n"
        "We received your application on April 20, 2026. "
        "Dates of service: 05/10/2026 - 05/12/2026. "
        "Your coverage will end on June 30, 2026."
    )
    _, f = run(text, dt.date(2026, 5, 6))
    assert [(x.date, x.kind) for x in f.dates] == [(dt.date(2026, 6, 30), "ends")]


def test_kinds_from_labels_and_cues():
    text = (
        "Date: 03/02/2026\n\n"
        "Payment Due Date: 03/20/2026\n"
        "Disconnection Date: 03/25/2026\n\n"
        "Your new rent of $900.00 will start on April 1, 2026. "
        "If you want a hearing, you must ask for a hearing by March 15, 2026. "
        "Your interview is scheduled for Tuesday, March 10, 2026 at 10:30 AM."
    )
    _, f = run(text)
    kinds = {x.date.isoformat(): x.kind for x in f.dates}
    assert kinds == {
        "2026-03-20": "payment_due",
        "2026-03-25": "ends",
        "2026-04-01": "starts",
        "2026-03-15": "respond_by",
        "2026-03-10": "appointment",
    }


def test_payment_received_by_is_a_payment_deadline():
    text = "Date: March 2, 2026\n\nUnless payment of the past-due amount is received by March 16, 2026, your service will be disconnected on or after March 18, 2026."
    _, f = run(text)
    assert [(x.date.day, x.kind) for x in f.dates] == [(16, "payment_due"), (18, "ends")]


def test_column_tables():
    text = (
        "Receipt Number          Notice Date\n"
        "LKM2690451873           05/19/2026\n\n"
        "Received Date           Priority Date\n"
        "04/28/2026              04/28/2026\n\n"
        "APPOINTMENT DATE AND TIME: 06/09/2026 at 10:00 AM"
    )
    clean, f = run(text, dt.date(2026, 5, 21))
    assert {fld.label for fld in table_fields(clean)} >= {"Receipt Number", "Notice Date"}
    assert f.letter_date == dt.date(2026, 5, 19)
    assert [x.date.isoformat() for x in f.dates] == ["2026-06-09"]
    assert "LKM2690451873" in [r.value for r in f.references]


def test_amounts_contacts_and_references():
    _clean, f = run(COURT_LETTER)
    assert [(a.value, a.kind) for a in f.amounts] == [(1250.0, "amount_due")]
    contacts = {(c.kind, c.normalized) for c in f.contacts}
    assert contacts == {
        ("phone", "3125550142"),
        ("phone", "8005550177"),
        ("tty", "711"),
        ("email", "clerk@lakemontcourts.example"),
        ("website", "lakemontcourts.example/selfhelp"),
    }
    assert [(r.kind, r.value) for r in f.references] == [("case", "SC-2026-004512")]


def test_fax_and_tty_labels():
    text = "Phone: (541) 555-0181     TTY: (541) 555-0182     Fax: (541) 555-0183"
    _, f = run(text)
    assert [(c.kind, c.normalized) for c in f.contacts] == [
        ("phone", "5415550181"),
        ("tty", "5415550182"),
        ("fax", "5415550183"),
    ]


def test_actions_consequences_rights():
    clean, f = run(COURT_LETTER)
    actions = [clean[p.quote.start : p.quote.end] for p in f.actions]
    consequences = [clean[p.quote.start : p.quote.end] for p in f.consequences]
    rights = [clean[p.quote.start : p.quote.end] for p in f.rights]
    assert any(a.startswith("You must appear at a hearing") for a in actions)
    assert any("Photo ID" in a for a in actions)  # list intro grouped with its items
    assert consequences == [
        "If you do not appear, the court may enter a default judgment against you."
    ]
    assert rights == ["You have the right to a free interpreter."]


def test_conditional_instruction_is_an_action_not_a_consequence():
    text = "If you cannot attend, you must call (217) 555-0103 to reschedule."
    _, f = run(text)
    assert len(f.actions) == 1
    assert f.consequences == []


def test_key_point_prefers_decisions():
    text = "Dear Ana,\n\nThank you for your letter. We have decided that you were overpaid $420.00 in benefits. Call us with questions."
    clean, f = run(text)
    assert any("We have decided" in clean[k.quote.start : k.quote.end] for k in f.key_points)


def test_quotes_are_exact_substrings():
    clean, f = run(COURT_LETTER)
    spans = [x.quote for x in f.dates] + [p.quote for p in f.actions + f.consequences + f.rights]
    for span in spans:
        assert 0 <= span.start < span.end <= len(clean)
