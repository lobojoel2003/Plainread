"""From letter text (or photos) to a full plain-language :class:`Explanation`."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from plainread import __version__, i18n, ocr
from plainread.classify import classify, find_sender
from plainread.dates import format_time
from plainread.extract import DateOrder, FoundPoint, Span, extract, find_terms
from plainread.grounding import make_quote
from plainread.models import (
    Amount,
    Contact,
    Explanation,
    GlossaryTerm,
    ImportantDate,
    OcrInfo,
    Point,
    Reference,
)
from plainread.plain import simplify
from plainread.text import normalize, reading_grade, segment

log = logging.getLogger(__name__)

LOW_CONFIDENCE = 70.0


@dataclass
class Upload:
    data: bytes
    filename: str = ""
    content_type: str | None = None


def urgency(days_left: int) -> str:
    if days_left < 0:
        return "overdue"
    if days_left == 0:
        return "today"
    if days_left <= 7:
        return "urgent"
    if days_left <= 30:
        return "soon"
    return "later"


def _href(kind: str, normalized: str, value: str) -> str | None:
    if kind in ("phone", "tty", "fax"):
        if len(normalized) == 10:
            return f"tel:+1{normalized}"
        return f"tel:{normalized}"
    if kind == "email":
        return f"mailto:{normalized}"
    if kind == "website":
        return value if value.lower().startswith(("http://", "https://")) else f"https://{value}"
    return None


_SMALL_WORDS = {"of", "and", "the", "for", "in", "on", "at", "to", "a", "an", "&"}


def _display_name(name: str) -> str:
    """Title-case names printed in ALL CAPS ("LAKEMONT COUNTY COURT")."""
    letters = [c for c in name if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return name
    words = []
    for i, word in enumerate(name.lower().split()):
        if i and word in _SMALL_WORDS:
            words.append(word)
        elif word in ("llc", "inc", "pc", "pllc", "lp", "llp", "usa", "us"):
            words.append(word.upper() if word not in ("inc",) else "Inc")
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def _points(text: str, found: list[FoundPoint]) -> list[Point]:
    out: list[Point] = []
    for p in found:
        quote = make_quote(text, p.quote.start, p.quote.end)
        if p.parts:
            # A list: keep the intro and put each item on its own line.
            intro, *items = (simplify(text[s.start : s.end]) for s in p.parts)
            plain = intro + "\n" + "\n".join("• " + item for item in items if item)
        else:
            plain = simplify(quote.text)
        out.append(Point(text=plain, quote=quote))
    return out


def explain_text(
    raw_text: str,
    *,
    language: str = "en",
    today: dt.date | None = None,
    date_order: DateOrder = "MDY",
    ai: object | None = None,
    ocr_info: OcrInfo | None = None,
    extra_warnings: Sequence[str] = (),
) -> Explanation:
    """Explain one letter given as text.

    ``ai`` is an optional :class:`plainread.llm.LocalModel`; when given, the
    explanation is rewritten in plainer words and translated, and every AI
    statement is checked against the letter.
    """
    lang = i18n.resolve(language)
    today = today or dt.date.today()
    text = normalize(raw_text)
    segments = segment(text)
    letter_type = classify(text) if text else "general"
    findings = extract(text, segments, today, date_order)
    warnings = list(extra_warnings)

    sender_seg = find_sender(segments)
    sender = (
        ", ".join(
            _display_name(" ".join(line.split()))
            for line in sender_seg.text.split("\n")
            if line.strip()
        )
        if sender_seg
        else None
    )
    sender_quote = make_quote(text, sender_seg.start, sender_seg.end) if sender_seg else None

    dates: list[ImportantDate] = []
    for f in findings.dates:
        quote = make_quote(text, f.quote.start, f.quote.end)
        days_left = (f.date - today).days
        date_text = i18n.format_date(f.date, lang)
        time_text = format_time(f.time) if f.time else None
        if time_text:
            date_text += " " + i18n.t(lang, "ui.at_time", time=time_text)
        note = None
        if f.note_key:
            values = dict(f.note_values)
            if isinstance(values.get("anchor"), dt.date):
                values["anchor"] = i18n.format_date(values["anchor"], lang)  # type: ignore[arg-type]
            note = i18n.t(lang, f"notes.{f.note_key}", **values)
        dates.append(
            ImportantDate(
                date=f.date,
                time=time_text,
                kind=f.kind,  # type: ignore[arg-type]
                label=i18n.t(lang, f"kinds.{f.kind}"),
                description=simplify(quote.text),
                date_text=date_text,
                days_left=days_left,
                urgency=urgency(days_left),  # type: ignore[arg-type]
                calculated=f.calculated,
                note=note,
                quote=quote,
            )
        )

    amounts = [
        Amount(
            value=a.value,
            display=a.display,
            kind=a.kind,  # type: ignore[arg-type]
            label=i18n.t(lang, f"amounts.{a.kind}"),
            quote=make_quote(text, a.quote.start, a.quote.end),
        )
        for a in findings.amounts
    ]
    contacts = [
        Contact(
            kind=c.kind,  # type: ignore[arg-type]
            value=c.value,
            normalized=c.normalized,
            label=i18n.t(lang, f"contacts.{c.kind}"),
            href=_href(c.kind, c.normalized, c.value),
            quote=make_quote(text, c.quote.start, c.quote.end),
        )
        for c in findings.contacts
    ]
    references = [
        Reference(
            kind=r.kind,  # type: ignore[arg-type]
            label=i18n.t(lang, f"references.{r.kind}"),
            value=r.value,
            quote=make_quote(text, r.quote.start, r.quote.end),
        )
        for r in findings.references
    ]
    glossary = [
        GlossaryTerm(
            term=g.term,
            meaning=g.meanings.get(lang) or g.meanings["en"],
            quote=make_quote(text, g.quote.start, g.quote.end),
        )
        for g in find_terms(text, segments, letter_type)
    ]
    actions = _points(text, findings.actions)
    consequences = _points(text, findings.consequences)
    rights = _points(text, findings.rights)
    key_points = _points(text, findings.key_points)

    grade = reading_grade(segments)
    reading_text = (
        i18n.t(lang, "reading_level", grade=round(grade)) if grade and grade >= 8 else None
    )

    if not text.strip():
        warnings.append(i18n.t(lang, "warnings.no_text"))
    if (
        ocr_info
        and ocr_info.used_ocr
        and ocr_info.confidence is not None
        and ocr_info.confidence < LOW_CONFIDENCE
    ):
        warnings.append(i18n.t(lang, "warnings.low_ocr_confidence"))

    explanation = Explanation(
        language=lang,
        direction=i18n.direction(lang),  # type: ignore[arg-type]
        engine="rules",
        letter_type=letter_type,
        letter_type_label=i18n.t(lang, f"letter_types.{letter_type}"),
        sender=sender,
        sender_quote=sender_quote,
        letter_date=findings.letter_date,
        today=today,
        summary=[],
        key_points=key_points,
        dates=dates,
        actions=actions,
        consequences=consequences,
        rights=rights,
        amounts=amounts,
        contacts=contacts,
        references=references,
        glossary=glossary,
        reading_grade=grade,
        reading_level_text=reading_text,
        warnings=warnings,
        disclaimer=i18n.t(lang, "warnings.not_advice"),
        ocr=ocr_info,
        source_text=text,
        version=__version__,
    )

    if ai is not None and text.strip():
        from plainread import llm

        assert isinstance(ai, llm.LocalModel)
        try:
            explanation = llm.enhance(explanation, ai)
        except llm.AIError as exc:
            log.warning("Local AI failed: %s", exc)
            explanation.warnings.append(i18n.t(lang, "warnings.ai_failed"))

    if explanation.engine == "rules" and lang != "en" and text.strip():
        explanation.warnings.append(i18n.t(lang, "warnings.english_sentences"))
    explanation.summary = build_summary(explanation, lang)
    return explanation


def build_summary(e: Explanation, lang: str) -> list[str]:
    """Short translated overview sentences built from the findings."""
    lines: list[str] = []
    if e.sender:
        lines.append(i18n.t(lang, "summary.from_sender", sender=e.sender))
    lines.append(i18n.t(lang, "summary.type", type=e.letter_type_label))
    if e.letter_date:
        lines.append(i18n.t(lang, "summary.dated", date=i18n.format_date(e.letter_date, lang)))
    if e.dates:
        upcoming = [x for x in e.dates if (x.days_left or 0) >= 0] or e.dates
        nxt = upcoming[0]
        values = {
            "date": nxt.date_text,
            "relative": i18n.relative_day(nxt.days_left or 0, lang),
        }
        lines.append(i18n.tn(lang, "summary.dates", len(e.dates), **values))
    else:
        lines.append(i18n.t(lang, "summary.no_dates"))
    if e.actions:
        lines.append(i18n.tn(lang, "summary.actions", len(e.actions)))
    else:
        lines.append(i18n.t(lang, "summary.no_actions"))
    due = [a for a in e.amounts if a.kind in ("amount_due", "overpayment")]
    if due:
        biggest = max(due, key=lambda a: a.value)
        lines.append(i18n.t(lang, "summary.money", amount=f"{biggest.display} ({biggest.label})"))
    return lines


def read_uploads(uploads: Sequence[Upload], ocr_lang: str = "eng") -> tuple[str, OcrInfo]:
    """OCR/parse every uploaded page and join the text in order."""
    texts: list[str] = []
    pages = 0
    confidences: list[tuple[float, int]] = []
    used_ocr = False
    for upload in uploads:
        result = ocr.read_file(upload.data, upload.filename, upload.content_type, ocr_lang)
        texts.append(result.text)
        pages += result.pages
        used_ocr = used_ocr or result.used_ocr
        if result.confidence is not None:
            confidences.append((result.confidence, result.pages))
    confidence = None
    if confidences:
        total_pages = sum(p for _, p in confidences)
        confidence = round(sum(c * p for c, p in confidences) / total_pages, 1)
    engine = "tesseract " + (ocr.tesseract_version() or "") if used_ocr else "pdf-text"
    info = OcrInfo(pages=pages, confidence=confidence, engine=engine.strip(), used_ocr=used_ocr)
    return "\n\n".join(t for t in texts if t.strip()), info


def explain_uploads(
    uploads: Sequence[Upload], *, ocr_lang: str = "eng", **kwargs: object
) -> Explanation:
    text, info = read_uploads(uploads, ocr_lang)
    return explain_text(text, ocr_info=info, **kwargs)  # type: ignore[arg-type]


def span_text(text: str, span: Span) -> str:
    return text[span.start : span.end]
