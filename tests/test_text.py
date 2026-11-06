from plainread.plain import simplify
from plainread.text import normalize, reading_grade, segment, syllables


def test_normalize_joins_hyphenated_words_and_trims():
    raw = "  Your deter-\nmination\r\nis ready.\n\n\n\nThanks\t!  "
    assert normalize(raw) == "Your determination\nis ready.\n\nThanks    !"


def test_segment_offsets_point_into_text():
    text = normalize("Dear Ana,\n\nPlease call us. We will help you.\n\nSincerely,\nThe Office")
    for seg in segment(text):
        assert text[seg.start : seg.end] == seg.text


def test_segment_splits_sentences_but_not_abbreviations():
    text = "Please arrive at 9:00 a.m. on Monday. Dr. Lee will see you at 123 Main St. in Room 4B. Bring your ID."
    sentences = [s.clean for s in segment(text)]
    assert sentences == [
        "Please arrive at 9:00 a.m. on Monday.",
        "Dr. Lee will see you at 123 Main St. in Room 4B.",
        "Bring your ID.",
    ]


def test_segment_splits_after_room_number_with_letter():
    text = "Go to Courtroom 4B. If you do not appear, you may lose."
    assert [s.clean for s in segment(text)] == [
        "Go to Courtroom 4B.",
        "If you do not appear, you may lose.",
    ]


def test_header_lines_stay_separate():
    text = "ACME HOSPITAL\nBilling Office\n123 Main Street\n\nAccount Number: 12345"
    segs = segment(text)
    assert [s.clean for s in segs] == [
        "ACME HOSPITAL",
        "Billing Office",
        "123 Main Street",
        "Account Number: 12345",
    ]
    assert all(s.is_line for s in segs)


def test_all_caps_heading_is_not_glued_to_next_sentence():
    text = "WHAT YOU MUST DO\nYou must repay the balance due of $1,820.00 by June 1, 2026. Call us."
    segs = [s.clean for s in segment(text)]
    assert segs[0] == "WHAT YOU MUST DO"
    assert segs[1].startswith("You must repay")


def test_bullets_become_their_own_segments():
    text = "Please bring:\n- Photo ID\n- Proof of income for the last\n  30 days\n- This letter"
    segs = [s.clean for s in segment(text)]
    assert "- Photo ID" in segs
    assert any(s.startswith("- Proof of income") for s in segs)


def test_reading_grade_is_high_for_legalese():
    legalese = (
        "Pursuant to the applicable administrative regulations, the Department has determined that "
        "your household's eligibility for continued assistance must be redetermined. Failure to "
        "furnish the requisite documentation within the prescribed timeframe will result in the "
        "termination of benefits without further notification. Additional information regarding "
        "your appeal rights is enclosed for your consideration and reference."
    )
    grade = reading_grade(segment(legalese))
    assert grade is not None
    assert grade >= 14


def test_syllables():
    assert syllables("the") == 1
    assert syllables("determination") >= 4


def test_simplify_rewrites_officialese():
    assert simplify("Please be advised that you are required to remit payment prior to May 1.") == (
        "You must send payment before May 1."
    )
    assert simplify("You have thirty (30) days to appeal.") == "You have 30 days to appeal."
    assert (
        simplify("- In the event that you need assistance, call us.")
        == "If you need help, call us."
    )
