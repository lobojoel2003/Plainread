"""Data models shared by the engine, the API and the web app.

Every fact Plainread reports carries a :class:`Quote`: the exact words from the
letter that support it, with character offsets into ``Explanation.source_text``.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

DateKind = Literal["respond_by", "hearing", "appointment", "payment_due", "ends", "starts", "other"]
Urgency = Literal["overdue", "today", "urgent", "soon", "later"]
ContactKind = Literal["phone", "tty", "fax", "email", "website"]
AmountKind = Literal["amount_due", "benefit", "overpayment", "charge", "paid", "other"]
ReferenceKind = Literal[
    "case",
    "claim",
    "account",
    "member",
    "notice",
    "reference",
    "invoice",
    "receipt",
    "policy",
    "client",
]
Source = Literal["rules", "ai"]


class Quote(BaseModel):
    """Exact words from the letter, located by character offsets."""

    text: str = Field(description="The words exactly as they appear in the letter.")
    start: int = Field(ge=0, description="Start offset in Explanation.source_text.")
    end: int = Field(ge=0, description="End offset (exclusive) in Explanation.source_text.")


class Point(BaseModel):
    """A plain-language statement backed by a quote."""

    text: str
    quote: Quote
    source: Source = "rules"


class ImportantDate(BaseModel):
    date: dt.date
    time: str | None = None
    kind: DateKind
    label: str = Field(description="Short translated label for the kind of date.")
    description: str = Field(description="Plain-language sentence about this date.")
    date_text: str = Field(description="The date written out in the chosen language.")
    days_left: int | None = None
    urgency: Urgency | None = None
    calculated: bool = Field(
        default=False, description="True when Plainread worked the date out from a period."
    )
    note: str | None = Field(default=None, description="How the date was worked out.")
    quote: Quote
    source: Source = "rules"


class Amount(BaseModel):
    value: float
    display: str
    kind: AmountKind
    label: str
    quote: Quote


class Contact(BaseModel):
    kind: ContactKind
    value: str = Field(description="As printed in the letter.")
    normalized: str = Field(description="Digits only for numbers; lowercase for email/web.")
    label: str
    href: str | None = None
    quote: Quote


class Reference(BaseModel):
    kind: ReferenceKind
    label: str
    value: str
    quote: Quote


class GlossaryTerm(BaseModel):
    term: str
    meaning: str
    quote: Quote


class OcrInfo(BaseModel):
    pages: int
    confidence: float | None = Field(
        default=None, description="Average word confidence from 0 to 100."
    )
    engine: str
    used_ocr: bool = True


class Explanation(BaseModel):
    """The full plain-language explanation of one letter."""

    language: str
    direction: Literal["ltr", "rtl"] = "ltr"
    engine: str
    letter_type: str
    letter_type_label: str
    sender: str | None = None
    sender_quote: Quote | None = None
    letter_date: dt.date | None = None
    today: dt.date
    summary: list[str]
    key_points: list[Point]
    dates: list[ImportantDate]
    actions: list[Point]
    consequences: list[Point]
    rights: list[Point]
    amounts: list[Amount]
    contacts: list[Contact]
    references: list[Reference]
    glossary: list[GlossaryTerm]
    reading_grade: float | None = None
    reading_level_text: str | None = None
    warnings: list[str]
    disclaimer: str
    ocr: OcrInfo | None = None
    source_text: str
    version: str

    def all_quotes(self) -> list[Quote]:
        """Every quote in the explanation (used by the grounding check)."""
        quotes: list[Quote] = [p.quote for p in self.key_points]
        quotes += [d.quote for d in self.dates]
        quotes += [p.quote for p in self.actions + self.consequences + self.rights]
        quotes += [a.quote for a in self.amounts]
        quotes += [c.quote for c in self.contacts]
        quotes += [r.quote for r in self.references]
        quotes += [g.quote for g in self.glossary]
        if self.sender_quote:
            quotes.append(self.sender_quote)
        return quotes
