import datetime as dt
import io

import pytest
from PIL import Image

from plainread import ocr, samples
from plainread.pipeline import Upload, explain_text, explain_uploads, read_uploads
from plainread.synth import render_letter

from .conftest import COURT_LETTER, TODAY


def test_sniff_type():
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="PNG")
    assert ocr.sniff_type(buffer.getvalue()) == "image/png"
    assert ocr.sniff_type(b"%PDF-1.7 ...") == "application/pdf"
    assert ocr.sniff_type(b"hello", "letter.txt") == "text/plain"
    with pytest.raises(ocr.UnsupportedFileError):
        ocr.sniff_type(b"\x00\x01", "x.bin")


def test_prepare_image_upscales_and_grays():
    small = Image.new("RGB", (600, 800), "white")
    prepared = ocr.prepare_image(small)
    assert prepared.mode == "L"
    assert max(prepared.size) >= 1800


def test_layout_keeps_columns():
    data = {
        "text": ["Receipt", "Number", "Notice", "Date", "LKM123", "05/19/2026"],
        "page_num": [1] * 6,
        "block_num": [1] * 6,
        "par_num": [1] * 6,
        "line_num": [1, 1, 1, 1, 2, 2],
        "left": [0, 90, 400, 480, 0, 400],
        "width": [80, 70, 70, 50, 70, 120],
    }
    lines = ocr._layout_text(data).splitlines()
    assert lines[0].index("Notice") == lines[1].index("05/19/2026")


def test_render_letter_is_deterministic():
    a = render_letter("Hello", seed=1).tobytes()
    b = render_letter("Hello", seed=1).tobytes()
    assert a == b


@pytest.mark.ocr
def test_photo_to_explanation():
    image = render_letter(COURT_LETTER, photo=True, seed=7)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    text, info = read_uploads([Upload(buffer.getvalue(), "page1.jpg")])
    assert "Lakemont" in text or "LAKEMONT" in text
    assert info.used_ocr
    assert info.pages == 1
    e = explain_uploads([Upload(buffer.getvalue(), "page1.jpg")], today=TODAY)
    assert e.letter_type == "court"
    assert e.ocr is not None
    assert e.ocr.confidence is not None


@pytest.mark.ocr
def test_multi_page_upload_keeps_order():
    pages = []
    for i, body in enumerate(
        ["PAGE ONE\n\nPlease call (312) 555-0142.", "PAGE TWO\n\nEmail help@demo.example."]
    ):
        buffer = io.BytesIO()
        render_letter(body, photo=False, seed=i).save(buffer, format="PNG")
        pages.append(Upload(buffer.getvalue(), f"p{i}.png"))
    text, info = read_uploads(pages)
    assert info.pages == 2
    assert text.index("ONE") < text.index("TWO")


@pytest.mark.parametrize("sample", [s["id"] for s in samples.list_samples()])
def test_samples_have_upcoming_dates(sample):
    today = dt.date(2026, 7, 1)
    letter = samples.get_sample(sample, today)
    assert "{{" not in letter["text"]
    e = explain_text(letter["text"], today=today)
    assert e.letter_date is not None
    assert e.letter_date < today
    assert e.dates
    assert all((d.days_left or 0) > 0 for d in e.dates)


def test_sample_weekday_placeholders_avoid_weekends():
    text = samples.fill_dates("{{w:+0}}", dt.date(2026, 3, 7))  # a Saturday
    assert text == "Monday, March 9, 2026"
