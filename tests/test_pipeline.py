import datetime as dt

import pytest

from plainread.grounding import grounding_rate, quote_is_valid
from plainread.pipeline import build_summary, explain_text, urgency

from .conftest import COURT_LETTER, TODAY


def test_explain_text_end_to_end():
    e = explain_text(COURT_LETTER, today=TODAY)
    assert e.letter_type == "court"
    assert e.sender == "Lakemont County Superior Court, Small Claims Division"
    assert e.letter_date == dt.date(2026, 2, 24)
    assert e.engine == "rules"
    assert (
        e.summary[0] == "This letter is from Lakemont County Superior Court, Small Claims Division."
    )
    assert any("2 important dates" in line for line in e.summary)
    hearing = next(d for d in e.dates if d.kind == "hearing")
    assert hearing.days_left == 18
    assert hearing.urgency == "soon"
    assert hearing.date_text == "Friday, March 20, 2026 at 9:00 AM"
    assert any(g.term == "default judgment" for g in e.glossary)
    assert e.disclaimer.startswith("Plainread helps you understand")


def test_every_quote_is_grounded():
    e = explain_text(COURT_LETTER, today=TODAY)
    assert grounding_rate(e) == 1.0
    for quote in e.all_quotes():
        assert quote_is_valid(e.source_text, quote)


def test_spanish_output():
    e = explain_text(COURT_LETTER, today=TODAY, language="es-MX")
    assert e.language == "es"
    assert e.letter_type_label == "Carta de la corte"
    hearing = next(d for d in e.dates if d.kind == "hearing")
    assert hearing.date_text.startswith("viernes, 20 de marzo de 2026")
    assert any("inglés" in w for w in e.warnings)  # sentences stay in English without AI
    assert e.glossary[0].meaning != ""


def test_arabic_is_right_to_left():
    e = explain_text(COURT_LETTER, today=TODAY, language="ar")
    assert e.direction == "rtl"


def test_empty_letter():
    e = explain_text("   ", today=TODAY)
    assert e.dates == []
    assert any("could not find any words" in w for w in e.warnings)


@pytest.mark.parametrize(
    ("days", "expected"),
    [(-1, "overdue"), (0, "today"), (3, "urgent"), (7, "urgent"), (20, "soon"), (31, "later")],
)
def test_urgency(days, expected):
    assert urgency(days) == expected


def test_summary_mentions_money_owed():
    text = "Date: March 2, 2026\n\nAmount Due: $412.37\n\nPlease pay by March 16, 2026."
    e = explain_text(text, today=TODAY)
    assert build_summary(e, "en")[-1] == "Money in this letter: $412.37 (Amount you owe)."


def test_list_actions_keep_items_on_separate_lines():
    e = explain_text(COURT_LETTER, today=TODAY)
    bring = next(a for a in e.actions if "Photo ID" in a.text)
    assert bring.text.splitlines()[1:] == ["• Photo ID", "• Any receipts or photos about your case"]
