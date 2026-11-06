import io

import pytest
from PIL import Image

from plainread.synth import render_letter

from .conftest import COURT_LETTER

# A tiny one-page PDF with a real text layer ("Please pay $40.00 by March 20, 2026.").
_PDF_TEXT = (
    "BT /F1 12 Tf 72 720 Td (Date: March 2, 2026. Please pay $40.00 by March 20, 2026.) Tj ET"
)


def make_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(_PDF_TEXT), _PDF_TEXT.encode()),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (number, body))
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    )
    return out.getvalue()


def test_index_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Plainread" in response.text
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert response.headers["x-frame-options"] == "DENY"
    assert client.head("/").status_code == 200


def test_static_assets(client):
    for path in (
        "/static/app.js",
        "/static/styles.css",
        "/static/icon.svg",
        "/manifest.webmanifest",
    ):
        assert client.get(path).status_code == 200, path


def test_health(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["version"]
    assert data["ai"]["enabled"] is False
    assert "available" in data["ocr"]
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_languages_and_locales(client):
    languages = client.get("/api/languages").json()
    assert len(languages) == 12
    assert client.get("/api/i18n/es").json()["_meta"]["code"] == "es"
    assert client.get("/api/i18n/unknown").json()["_meta"]["code"] == "en"


def test_samples(client):
    samples = client.get("/api/samples").json()
    assert {s["id"] for s in samples} == {
        "court-summons",
        "hospital-bill",
        "benefits-renewal",
        "utility-shutoff",
    }
    sample = client.get("/api/samples/court-summons?today=2026-03-02").json()
    assert "February 26, 2026" in sample["text"]  # letter dated 4 days before "today"
    assert client.get("/api/samples/nope").status_code == 404


def test_explain_text_form(client):
    response = client.post(
        "/api/explain", data={"text": COURT_LETTER, "language": "en", "today": "2026-03-02"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["letter_type"] == "court"
    assert [d["date"] for d in data["dates"]] == ["2026-03-16", "2026-03-20"]


def test_explain_text_json(client):
    response = client.post(
        "/api/explain/text", json={"text": COURT_LETTER, "language": "fr", "today": "2026-03-02"}
    )
    assert response.status_code == 200
    assert response.json()["language"] == "fr"


def test_explain_requires_input(client):
    response = client.post("/api/explain", data={"language": "es"})
    assert response.status_code == 400
    assert "Agregue" in response.json()["detail"] or "texto" in response.json()["detail"]


def test_explain_rejects_unknown_files(client):
    response = client.post(
        "/api/explain", files={"files": ("x.bin", b"\x00\x01garbage", "application/octet-stream")}
    )
    assert response.status_code == 415


def test_explain_rejects_big_files(settings):
    from fastapi.testclient import TestClient

    from plainread.api import create_app

    settings.max_upload_mb = 0
    small = TestClient(create_app(settings))
    response = small.post("/api/explain", files={"files": ("a.txt", b"hello world", "text/plain")})
    assert response.status_code == 413


def test_explain_text_file_upload(client):
    response = client.post(
        "/api/explain",
        files={"files": ("letter.txt", COURT_LETTER.encode(), "text/plain")},
        data={"today": "2026-03-02"},
    )
    assert response.status_code == 200
    assert response.json()["ocr"]["used_ocr"] is False


def test_explain_pdf_with_text_layer(client):
    response = client.post(
        "/api/explain",
        files={"files": ("letter.pdf", make_pdf(), "application/pdf")},
        data={"today": "2026-03-05"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ocr"]["engine"] == "pdf-text"
    assert [(d["date"], d["kind"]) for d in data["dates"]] == [("2026-03-20", "payment_due")]


@pytest.mark.ocr
def test_explain_photo(client):
    image = render_letter(COURT_LETTER, photo=True, seed=3)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    response = client.post(
        "/api/explain",
        files={"files": ("photo.jpg", buffer.getvalue(), "image/jpeg")},
        data={"today": "2026-03-02", "language": "en"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ocr"]["used_ocr"] is True
    assert data["ocr"]["confidence"] > 70
    assert "2026-03-20" in [d["date"] for d in data["dates"]]
    assert "SC-2026-004512" in [r["value"] for r in data["references"]]


def test_ocr_unavailable_is_reported(client, monkeypatch):
    from plainread import ocr

    monkeypatch.setattr(ocr, "tesseract_command", lambda: None)
    image = Image.new("RGB", (50, 50), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    response = client.post(
        "/api/explain", files={"files": ("a.png", buffer.getvalue(), "image/png")}
    )
    assert response.status_code == 503
    assert "Tesseract" in response.json()["detail"]


def test_calendar(client):
    data = client.post(
        "/api/explain/text", json={"text": COURT_LETTER, "today": "2026-03-02"}
    ).json()
    response = client.post("/api/calendar", json={"dates": data["dates"], "sender": data["sender"]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.text.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20260320T090000" in response.text
