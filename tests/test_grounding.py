from plainread.grounding import locate

LETTER = "You must return the form\nby June 3, 2026.  If you don’t, your coverage will end on June 30, 2026."


def test_exact():
    start, end = locate(LETTER, "your coverage will end")
    assert LETTER[start:end] == "your coverage will end"


def test_whitespace_case_and_quote_marks_are_ignored():
    span = locate(LETTER, "you must RETURN the form by june 3, 2026")
    assert span is not None
    assert LETTER[span[0] : span[1]].startswith("You must return the form\nby June 3")
    assert locate(LETTER, "If you don't, your coverage") is not None


def test_small_ocr_differences_are_tolerated():
    span = locate(LETTER, "If you don't, your coverage wi11 end on June 30, 2026.")
    assert span is not None


def test_invented_quotes_are_rejected():
    assert locate(LETTER, "You owe $5,000 and must go to court tomorrow.") is None
    assert locate(LETTER, "end") is None  # too short to be meaningful
    assert locate(LETTER, "") is None
