"""Rule-based extraction of everything a reader needs from a letter.

The rules engine always runs, needs no AI model, and only ever reports things
it can point to in the letter. The optional local AI layer (:mod:`plainread.llm`)
improves the wording and translates it, but never replaces this ground truth.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from itertools import pairwise
from typing import Literal

from plainread import dates as d
from plainread.text import Segment, collapse

DateOrder = Literal["MDY", "DMY"]


@dataclass
class Span:
    start: int
    end: int


@dataclass
class FoundDate:
    date: dt.date
    kind: str
    quote: Span
    time: dt.time | None = None
    calculated: bool = False
    note_key: str | None = None
    note_values: dict[str, object] = field(default_factory=dict)
    year_guessed: bool = False


@dataclass
class FoundPoint:
    quote: Span
    category: Literal["action", "consequence", "right", "key"]
    score: float = 0.0
    parts: list[Span] = field(default_factory=list)  # list intro + items


@dataclass
class FoundAmount:
    value: float
    display: str
    kind: str
    quote: Span


@dataclass
class FoundContact:
    kind: str
    value: str
    normalized: str
    quote: Span


@dataclass
class FoundReference:
    kind: str
    value: str
    quote: Span


@dataclass
class FoundTerm:
    term: str
    meanings: dict[str, str]
    quote: Span


@dataclass
class Findings:
    letter_date: dt.date | None
    letter_date_span: Span | None
    dates: list[FoundDate]
    actions: list[FoundPoint]
    consequences: list[FoundPoint]
    rights: list[FoundPoint]
    key_points: list[FoundPoint]
    amounts: list[FoundAmount]
    contacts: list[FoundContact]
    references: list[FoundReference]


# --------------------------------------------------------------------------- #
# Column tables: labels on one line, values on the next
# --------------------------------------------------------------------------- #

_COLUMN = re.compile(r"\S+(?: \S+)*")


@dataclass
class TableField:
    label: str
    start: int
    end: int


def table_fields(text: str) -> list[TableField]:
    """Read layouts like ``Receipt Number    Notice Date`` / ``LKM123    05/19/2026``."""
    fields: list[TableField] = []
    offsets = []
    pos = 0
    for line in text.split("\n"):
        offsets.append((pos, line))
        pos += len(line) + 1
    for (_, header), (v_start, values) in pairwise(offsets):
        if "  " not in header or "  " not in values.strip():
            continue
        h_cols = [(m.start(), m.group()) for m in _COLUMN.finditer(header)]
        v_cols = [(m.start(), m.group()) for m in _COLUMN.finditer(values)]
        if len(h_cols) < 2 or len(v_cols) < 2:
            continue
        if any(re.search(r"\d|[:$@]", label) or len(label.split()) > 4 for _, label in h_cols):
            continue
        for h_start, label in h_cols:
            for col_start, value in v_cols:
                if abs(col_start - h_start) <= 3:
                    fields.append(
                        TableField(label, v_start + col_start, v_start + col_start + len(value))
                    )
                    break
    return fields


# --------------------------------------------------------------------------- #
# Letter date
# --------------------------------------------------------------------------- #

_LETTER_DATE_LABEL = re.compile(
    r"^\s*(?:(?:notice|letter|mailing|mail|statement|issue|issued|print|printed|notification|"
    r"decision|determination|bill(?:ing)?|invoice|correspondence|summons)\s+)?"
    r"date(?:\s+(?:of\s+(?:notice|letter|this\s+(?:notice|letter)|mailing|issue)|mailed|issued|sent|printed))?"
    r"\s*[:\-]|^\s*(?:mailed|sent|issued)(?:\s+on)?\s*:",
    re.IGNORECASE,
)


_QUALIFIED_DATE_LABEL = re.compile(
    r"^\s*(?:notice|letter|mailing|mail|statement|issue|issued|print|printed|notification|decision|"
    r"determination|bill(?:ing)?|invoice|correspondence|summons)\s+date\b|^\s*date\s+(?:of\s+(?:notice|letter|"
    r"this|mailing|issue)|mailed|issued|sent|printed)\b|^\s*(?:mailed|sent|issued)\b",
    re.IGNORECASE,
)
_EVENT_FIELD = re.compile(
    r"^\s*(?:time|location|place|where|room|address|arrival|check-in|with)\s*:", re.I
)


def _find_letter_date(
    text: str,
    segments: list[Segment],
    found: list[d.DateMatch],
    today: dt.date,
    tables: list[TableField],
) -> tuple[dt.date | None, Span | None]:
    def first_date(start: int, end: int) -> tuple[dt.date, Span] | None:
        for m in found:
            if start <= m.start < end and m.year is not None:
                value, _ = m.resolve(today)
                if value:
                    return value, Span(m.start, m.end)
        return None

    # 1. "Notice Date:", "Mailing Date:", "Date of this notice:" always win.
    for seg in segments[:40]:
        if _QUALIFIED_DATE_LABEL.match(seg.text) and (hit := first_date(seg.start, seg.end)):
            return hit
    for field_ in tables:
        if (
            field_.start <= len(text) * 0.4
            and _QUALIFIED_DATE_LABEL.match(field_.label)
            and (hit := first_date(field_.start, field_.end))
        ):
            return hit
    candidates: list[tuple[int, dt.date, Span]] = []
    # 2. A bare "Date:" field, unless it belongs to an appointment block
    #    ("Date: ... / Time: ... / Location: ...").
    for i, seg in enumerate(segments[:40]):
        if _LETTER_DATE_LABEL.match(seg.text) and (hit := first_date(seg.start, seg.end)):
            nearby = segments[max(0, i - 2) : i + 3]
            if any(_EVENT_FIELD.match(n.text) for n in nearby):
                continue
            candidates.append((hit[1].start, *hit))
    # 3. A date standing on its own line near the top (classic letter layout).
    cutoff = max(400, len(text) // 3)
    for m in found:
        if m.start > cutoff:
            break
        line_start = text.rfind("\n", 0, m.start) + 1
        line_end = text.find("\n", m.end)
        line = text[line_start : line_end if line_end != -1 else len(text)].strip()
        rest = line.replace(m.text, "").strip(" ,.-")
        if len(rest) <= 25 and ":" not in rest and not _NOT_LETTER_DATE.search(line):
            value, _ = m.resolve(today)
            if value and m.year is not None:
                candidates.append((m.start, value, Span(m.start, m.end)))
    if candidates:
        _, value, span = min(candidates, key=lambda c: c[0])
        return value, span
    # 4. "...stopped by today, Tue., Sept. 8, 2026, ..."
    for m in found:
        if m.start > cutoff:
            break
        if re.search(r"\btoday\b[^.\n]{0,12}$", text[max(0, m.start - 30) : m.start], re.I):
            value, _ = m.resolve(today)
            if value and m.year is not None:
                return value, Span(m.start, m.end)
    return None, None


_NOT_LETTER_DATE = re.compile(
    r"\b(?:due|birth|dob|born|service|hearing|appointment|interview|effective|expires?|"
    r"deadline|respond|return|by|before|until|through|disconnect|cancel|period|from|to)\b",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Date kinds
# --------------------------------------------------------------------------- #

_KIND_CUES: dict[str, tuple[re.Pattern[str], float]] = {
    "hearing": (
        re.compile(
            r"\bhearings?\b|\btrial\b|\bcourtroom\b|\barraignment\b|\bappear(?:ance)?\b|"
            r"\bcourt date\b|\bbefore the (?:judge|court)\b|\bmediation\b|\bpre-?trial\b|\bdocket call\b",
            re.I,
        ),
        0.55,
    ),
    "appointment": (
        re.compile(
            r"\bappointments?\b|\binterview\b|\bmeeting\b|\bscheduled\b|\bvisit\b|\bexam(?:ination)?\b|"
            r"\bbiometrics?\b|\breport(?:ing)?\s+(?:to|for|on|date)\b|\bjury (?:service|duty)\b|\borientation\b|"
            r"\bconference\b|\barriv(?:e|al)\b|\bcheck[- ]in\b|\bprocedure\b|\bcolonoscopy\b|\bsession\b|"
            r"\bserve as a juror\b|\bjuror\b",
            re.I,
        ),
        1.0,
    ),
    "payment_due": (
        re.compile(
            r"\bpay(?:ment|able|ing)?s?\b|\bamount due\b|\bdue date\b|\bbalance\b|\bremit\b|"
            r"\bminimum due\b|\bpaid in full\b|\bdue\b",
            re.I,
        ),
        0.8,
    ),
    "ends": (
        re.compile(
            r"\b(?:will|shall|may|would|is going to)\s+(?:be\s+)?(?:end(?:ed)?|stop(?:ped)?|terminated?|"
            r"closed?|cancell?ed|expire|discontinued|suspended|disconnected|shut off|lapse)\b|"
            r"\bends?\b|\bexpir(?:es|ation|e|ing)\b|\bcancell?ation\b|\bdisconnect(?:ion|ed)?\b|"
            r"\bshut ?off\b|\bterminat(?:e|ion|ed|es)\b|\blast day\b|\bdiscontinu\w*|\bthrough\b|"
            r"\bclos(?:e|es|ed|ing)\b|\blapse\b|\bno longer\b|\bcancel(?:l)?ed\b|\bvalid until\b",
            re.I,
        ),
        0.8,
    ),
    "starts": (
        re.compile(
            r"\b(?:start|begin|increase|decrease|change)s?\b|\beffective\b|\bbeginning\b|\bstarting\b|"
            r"\btakes? effect\b|\bnew (?:amount|rent|payment|monthly|benefit)\b|\bas of\b|\bdeposit(?:ed)?\b|\bwill be (?:increased|reduced|adjusted)\b",
            re.I,
        ),
        0.9,
    ),
    "respond_by": (
        re.compile(
            r"\breturn(?:ed)?\b|\bsubmit(?:ted)?\b|\bsend\b|\bmail(?:ed)?\b|\brespon(?:d|se)\b|\breply\b|"
            r"\banswer\b|\bappeal\b|\brequest(?:ed)?\b|\bask for\b|\bdispute\b|\bapply\b|\bapplication\b|"
            r"\brenew(?:al)?\b|\bcomplete(?:d)?\b|\bsign(?:ed)?\b|\bfax(?:ed)?\b|\bupload\b|\bturn in\b|"
            r"\bprovide\b|\bfile[ds]?\b|\bfiling\b|\bregister\b|"
            r"\bnotify\b|\bcontact\b|\bcall\b|\breschedule\b|\bobject(?:ion)?\b|\bpostpone\b|\bdefer\b|"
            r"\bclaim\b|\bconfirm\b|\bverify\b|\benroll\b|\bdocuments?\b|\bforms?\b",
            re.I,
        ),
        1.0,
    ),
}
_GENERIC_DEADLINE = re.compile(
    r"\bby\b|\bbefore\b|\bno later than\b|\bnot later than\b|\bon or before\b|\bdeadline\b|\buntil\b|"
    r"\breceive[ds]?\b|\bpostmark(?:ed)?\b",
    re.I,
)
_REQUEST_BEFORE = re.compile(
    r"\b(?:request|ask(?:ing)? for|apply for|file for|want|asking|right to)\s+(?:a|an|the|your)?\s*"
    r"(?:\w+\s+){0,2}$",
    re.I,
)
_LABEL = re.compile(r"^\s*(?P<label>[A-Za-z][A-Za-z0-9 /&()'.\-]{1,50}?)\s*:\s*")
_EXCLUDE_DATE = re.compile(
    r"\bdate of birth\b|\bdob\b|\bborn\b|\bbirth ?date\b|\bdates? of service\b|\bservice dates?\b|"
    r"\bdate of (?:loss|injury|accident|incident|admission|discharge|visit)\b|\bstatement (?:date|period)\b|"
    r"\bbilling (?:date|period)\b|\b(?:statement|billing|service|pay|reporting|coverage) period\b|"
    r"\bperiod (?:from|of|beginning)\b|\bincurred\b|\bwe received\b|\breceived (?:on|your)\b|"
    r"\b(?:we )?sent (?:on|you)\b|\bdated\b|\bsince\b|\bfiled on\b|"
    r"\bwas (?:mailed|sent|filed|issued|received|served|made)\b|\bprint(?:ed)? (?:date|on)\b|\brev(?:ised)?\b|"
    r"\blast (?:payment|paid)\b|\bpayment received\b|\bon file\b|\bopened\b|\bdate of (?:last|first)\b|"
    r"\bcharged off\b|\bdelinquency date\b|\bseparation\b|\bhired\b|\bworked\b|\bwere paid\b",
    re.I,
)


def _kind_for(context: str, pos: int, end: int) -> tuple[str, float]:
    """Pick the kind whose cue words sit closest to the date at ``pos``."""
    best_kind, best_score = "other", 1e9
    for kind, (pattern, weight) in _KIND_CUES.items():
        for m in pattern.finditer(context):
            if m.start() >= pos and m.end() <= end:
                continue
            appear_elsewhere = (
                kind == "hearing"
                and m.group(0).lower().startswith("appear")
                and (
                    re.search(
                        r"\b(?:interview|appointment|exam|meeting|biometric|fingerprint)",
                        context[m.end() : m.end() + 60],
                        re.I,
                    )
                    or not re.search(r"\bcourt|\bjudge|\bhearing|\btrial|\bcase\b", context, re.I)
                )
            )
            if kind == "hearing" and _REQUEST_BEFORE.search(
                context[max(0, m.start() - 40) : m.start()]
            ):
                continue  # "ask for a hearing by ..." is a deadline
            if m.end() <= pos:
                gap = context[m.end() : pos]
                dist = float(len(gap))
            else:
                gap = context[end : m.start()]
                dist = len(gap) * 1.4
            if re.search(r"[,;]|\bunless\b|\bif\b|\bor\b", gap):
                dist += 18
            if "\n\n" in gap or re.search(r"[.!?]\s", gap):
                dist += 60
            score = dist * weight
            if (
                kind == "payment_due"
                and m.group(0).lower() == "due"
                and not re.search(r"\$|\bpay|\bamount|\bbalance", context, re.I)
            ):
                kind_eff = "respond_by"
            elif appear_elsewhere:
                # "appear for your interview" / "appear at the support center"
                kind_eff, score = "appointment", dist
            else:
                kind_eff = kind
            if score < best_score:
                best_kind, best_score = kind_eff, score
    # "by", "before", "received by"... say it is a deadline but not what kind.
    # They only decide when no specific cue word is nearby.
    if best_score > 45:
        for m in _GENERIC_DEADLINE.finditer(context):
            if m.end() <= pos and pos - m.end() < 40:
                best_kind, best_score = "respond_by", float(pos - m.end())
    return best_kind, best_score


def _label_kind(label: str) -> str | None:
    label = label.lower()
    for kind, words in (
        ("hearing", ("hearing", "trial", "court date", "arraignment", "appearance")),
        ("payment_due", ("payment due", "due date", "pay by", "amount due", "payment date")),
        (
            "ends",
            (
                "disconnect",
                "shut",
                "cancel",
                "termination",
                "end date",
                "expir",
                "last day",
                "coverage end",
            ),
        ),
        ("starts", ("effective", "start", "begin", "change date")),
        (
            "appointment",
            (
                "appointment",
                "interview",
                "meeting",
                "report",
                "exam",
                "visit",
                "biometric",
                "procedure",
                "arrival",
            ),
        ),
        (
            "respond_by",
            (
                "respond",
                "response",
                "return",
                "reply",
                "deadline",
                "due",
                "submit",
                "appeal",
                "answer",
                "renew",
            ),
        ),
    ):
        if any(w in label for w in words):
            return kind
    return None


def _context(segments: list[Segment], index: int) -> tuple[str, int]:
    """The segment text, plus the previous short lines when it is a bare field."""
    seg = segments[index]
    parts = [seg.text]
    offset = 0
    if seg.is_line or seg.words <= 6:
        j = index - 1
        while j >= 0 and len(parts) < 3:
            prev = segments[j]
            if prev.block < seg.block - 1:
                break
            if not (prev.is_line or prev.words <= 8 or prev.clean.endswith(":")):
                break
            parts.insert(0, prev.text)
            offset += len(prev.text) + 1
            j -= 1
    return "\n".join(parts), offset


def _attach_time(text: str, segments: list[Segment], index: int, m: d.DateMatch) -> dt.time | None:
    seg = segments[index]
    for t in d.find_times(seg.text):
        abs_start = seg.start + t.start
        if m.end <= abs_start <= m.end + 70 or m.start - 45 <= abs_start + len(t.text) <= m.start:
            between = text[m.end : abs_start] if abs_start >= m.end else ""
            if re.search(r"\bthrough\b|\bfriday\b|\bhours\b|\bopen\b|\bto\b\s*$", between, re.I):
                continue
            return t.value
    # "Date: ..." then "Time: ..." on the next line.
    for nxt in segments[index + 1 : index + 3]:
        if nxt.block > seg.block + 1:
            break
        if re.match(r"^\s*(?:time|hora|at)\b", nxt.text, re.I) or (
            nxt.is_line
            and re.match(r"^\s*(?:check[- ]in|arrival|start)\s*(?:time)?\s*:", nxt.text, re.I)
        ):
            times = d.find_times(nxt.text)
            if times:
                return times[0].value
    return None


def _segment_index(segments: list[Segment], offset: int) -> int | None:
    for i, seg in enumerate(segments):
        if seg.start <= offset < seg.end:
            return i
    return None


def _find_dates(
    text: str,
    segments: list[Segment],
    found: list[d.DateMatch],
    letter_date: dt.date | None,
    letter_span: Span | None,
    today: dt.date,
    tables: list[TableField],
) -> list[FoundDate]:
    results: list[FoundDate] = []
    reference = letter_date or today
    explicit_segments: set[int] = set()
    for m in found:
        if letter_span and m.start == letter_span.start:
            continue
        idx = _segment_index(segments, m.start)
        if idx is None:
            continue
        seg = segments[idx]
        value, guessed = m.resolve(reference)
        if value is None:
            continue
        if letter_date and value <= letter_date:
            continue
        if not letter_date and value < today - dt.timedelta(days=45):
            continue
        local_start = m.start - seg.start
        cell = next((f for f in tables if f.start <= m.start < f.end), None)
        if cell is not None:
            # A date in a column table takes its meaning from the column label.
            kind_from_label = _label_kind(cell.label)
            if kind_from_label is None:
                continue
            explicit_segments.add(idx)
            results.append(
                FoundDate(
                    date=value,
                    kind=kind_from_label,
                    quote=Span(seg.start, seg.end),
                    year_guessed=guessed,
                )
            )
            continue
        window = seg.text[max(0, local_start - 45) : local_start + len(m.text) + 12]
        if _EXCLUDE_DATE.search(window):
            # A real deadline cue right before the date wins over a distractor
            # further away ("must be received by", "no later than").
            near = seg.text[max(0, local_start - 18) : local_start]
            if not re.search(r"\b(?:by|before|than|on|until)\s*$", near, re.I) or re.search(
                r"\b(?:born|birth|dob|service|since|dated|period)\b", window, re.I
            ):
                continue
        context, offset = _context(segments, idx)
        pos = offset + local_start
        kind: str | None = None
        label_m = _LABEL.match(seg.text)
        if label_m and label_m.end() <= local_start + 1:
            kind = _label_kind(label_m.group("label"))
        if kind is None:
            kind, _ = _kind_for(context, pos, pos + len(m.text))
        explicit_segments.add(idx)
        results.append(
            FoundDate(
                date=value,
                kind=kind,
                quote=Span(seg.start, seg.end),
                time=_attach_time(text, segments, idx, m),
                year_guessed=guessed,
                note_key="year_guessed" if guessed else None,
                note_values={"year": value.year} if guessed else {},
            )
        )

    # "by 5 p.m. on the 14th" (needs the letter date to know the month).
    if letter_date is not None:
        taken = [(m.start, m.end) for m in found]
        for day_match in d.find_day_only(text):
            if any(s <= day_match.start < e for s, e in taken):
                continue
            day_value = day_match.resolve(letter_date)
            idx = _segment_index(segments, day_match.start)
            if day_value is None or idx is None or day_value <= letter_date:
                continue
            seg = segments[idx]
            context, offset = _context(segments, idx)
            pos = offset + (day_match.start - seg.start)
            kind, _ = _kind_for(context, pos, pos + len(day_match.text))
            results.append(
                FoundDate(
                    date=day_value,
                    kind=kind,
                    quote=Span(seg.start, seg.end),
                    year_guessed=True,
                )
            )
            explicit_segments.add(idx)

    for p in d.find_periods(text):
        idx = _segment_index(segments, p.start)
        if idx is None or idx in explicit_segments:
            continue
        seg = segments[idx]
        prefix = text[seg.start : p.start]
        if re.search(
            r"\b(?:we|it|they|this office|the (?:court|office|agency|department|plan|company))\s+"
            r"(?:will|may|can|should|usually|normally)\s+(?:\w+\s+){0,2}?(?:make|decide|send|review|process|"
            r"respond|reply|contact|notify|mail|take|issue|receive|refund|credit|get)\b|"
            r"\ballow\b|\bprocessing\b|\bplease wait\b|\bwait\b|"
            r"\bwill be (?:issued|made|sent|mailed|processed|reviewed|decided|completed)\b",
            prefix,
            re.I,
        ):
            continue
        if letter_date:
            base = letter_date
            note = "calc_from_receipt" if p.anchor == "receipt" else "calc_days_from_letter"
        else:
            base = today
            note = "calc_from_today"
        if p.business:
            note = "calc_business_days"
        value = d.add_days(base, p.days, p.business)
        context, offset = _context(segments, idx)
        pos = offset + (p.start - seg.start)
        kind, _ = _kind_for(context, pos, pos + len(p.text))
        results.append(
            FoundDate(
                date=value,
                kind=kind,
                quote=Span(seg.start, seg.end),
                calculated=True,
                note_key=note,
                note_values={"count": p.days, "anchor": base},
            )
        )

    # One entry per (date, kind); keep the first mention.
    unique: dict[tuple[dt.date, str], FoundDate] = {}
    for item in results:
        key = (item.date, item.kind)
        if key not in unique:
            unique[key] = item
        elif item.time and not unique[key].time:
            unique[key].time = item.time
    ordered = sorted(unique.values(), key=lambda f: (f.date, f.quote.start))
    return ordered


# --------------------------------------------------------------------------- #
# Actions, consequences, rights and key points
# --------------------------------------------------------------------------- #

_BOILERPLATE = re.compile(
    r"\bdoes not discriminate\b|\bnondiscrimination\b|\bnon-discrimination\b|\bcivil rights\b|"
    r"\bcomplies with applicable\b|\bany information obtained will be used\b|\bpage \d+ of \d+\b|"
    r"\bthis communication is from a debt collector\b|\bequal opportunity\b|\bpenalty of perjury\b|"
    r"\bprivacy act\b|\bpaperwork reduction\b",
    re.I,
)
_TAGLINE = re.compile(
    r"\b(?:usted|llame|gratis|gratuitos?|atención|ayuda|idioma|si habla|servicios|disponibles|"
    r"vous|appelez|gratuit|nou|kreyòl|tiếng|xin|thông|bạn|有|您|请|한국어|전화|русский|звоните|"
    r"tagalog|tumawag|libre)\b",
    re.I,
)
_RIGHT_STRONG = re.compile(
    r"\byou (?:also )?have (?:the )?rights?\b|\bmay (?:request|ask for|file) (?:a|an)\b|"
    r"\bwe (?:must|will) (?:stop|send|give|tell|provide|respond|not)\b|\bcontinue to (?:pay|receive|get)\b|"
    r"\baccommodations?\b|\bdisability-related\b|"
    r"\byou(?:\s+or\s+(?:your\s+)?\w+(?:\s+\w+)?)? (?:may|can|could) (?:also )?(?:ask|request|appeal|file|get|have|bring|"
    r"apply|dispute|seek|obtain|qualify|be (?:eligible|able)|choose to (?:appeal|request)|postpone|defer|reschedule|"
    r"contact|call)\b|\bright to\b|\byour rights\b|\b(?<!toll-)(?<!toll )free\b|\bat no (?:cost|charge)\b|"
    r"\binterpret(?:er|ers|ation|ing)\b|\blanguage (?:assistance|services|help|access)\b|\blegal (?:aid|services|help)\b|"
    r"\breasonable accommodation\b|\bexternal review\b|\bfair hearing\b|\bombudsman\b|\badvocate\b|"
    r"\bif you (?:disagree|do not agree|don't agree|think (?:we|this|the))\b|\bprohibit\w*\b|\bprotect\w*\b",
    re.I,
)
_RIGHT_WEAK = re.compile(
    r"\bpayment plan\b|\binstallment\b|\bfinancial assistance\b|\bcharity care\b|\bwaiver\b|"
    r"\bmedical (?:certificate|certification)\b|\bexemptions?\b|\bexempt\b|\bpostpone(?:ment)?\b|\bdefer(?:ral)?\b|"
    r"\bvalidation\b|\bverification of (?:the|this) debt\b|\boriginal creditor\b|\bexcused\b|"
    r"\bcomplaint\b|\breconsideration\b|\battorney\b|\blawyer\b",
    re.I,
)
_EXPLICIT_RIGHT = re.compile(
    r"\byou have the right\b|\bfree of charge\b|\bat no (?:cost|charge)\b|\binterpreter\b|\bcontinue to (?:pay|receive)\b",
    re.I,
)
_LOSE_RIGHT = re.compile(r"\blose (?:your|the|any) right", re.I)
_CONSEQUENCE_START = re.compile(
    r"^(?:if (?:you|we|the court|the clerk|payment|the (?:form|balance|amount|full amount|information|documents?|bill|"
    r"past[- ]due amount|rent|payment|request))\b[^.]{0,80}?\b(?:do not|don't|does not|doesn't|fail|fails|failed|miss|"
    r"are not|is not|isn't|aren't|choose not|ignore|have not|has not|did not|not)\b|failure to|failing to|unless\b|"
    r"if no (?:payment|response|answer|appeal|request|form)|otherwise\b|without (?:your|a) (?:response|payment)|"
    r"if (?:your|the) (?:service|account|coverage|policy|benefits?|case|claim|license|lease|tenancy|application|"
    r"electricity|power|gas|water)\b[^.,]{0,30}\b(?:is|are|has been|have been|gets|was)\s+(?:disconnected|terminated|"
    r"cancell?ed|closed|denied|suspended|referred|sent|reported|ended|stopped|shut off))",
    re.I,
)
_CONSEQUENCE_STRONG = re.compile(
    r"\b(?:may|will|could|can) result in\b|\bresult(?:s)? in\b|\bdefault judgment\b|\bjudgment by default\b|"
    r"\bwithout further notice\b|\bwarrant\b|\bcontempt\b|\blegal action\b|\bsent to collections?\b|"
    r"\breferred to (?:a |an |our )?(?:outside )?collection|\bcredit (?:report|bureau)s?\b|\bevict(?:ion|ed)?\b|"
    r"\bdecide against\b|\brule against\b|\bjudgment against\b|\b(?:may|will) be (?:held )?responsible for\b|"
    r"\blapse in\b|\bwithout coverage\b|\blose (?:your|the) (?:right|coverage|benefits?|home|apartment|license|place)\b|"
    r"\bfined\b|\bfound guilty\b|\bliens?\b|\blevy\b|\breconnection fee\b",
    re.I,
)
_CONSEQUENCE_WEAK = re.compile(
    r"\b(?:may|will|could|would|might)\s+(?:also\s+)?(?:lose|be (?:evicted|garnished|fined|arrested|charged|sued|"
    r"referred|reported|terminated|denied|closed|cancell?ed|disconnected|shut off|suspended|reduced|stopped|"
    r"ended|removed|considered|required to (?:repay|pay)|held|added|assessed|delayed|dismissed|withheld))\b|"
    r"\b(?:will|may|could)\s+(?:also\s+)?(?:stop|end|close|cancel|deny|terminate|garnish|disconnect|report|refer|"
    r"charge|add|assess|file|issue|take|begin|start|lose|suspend|remove|withhold|keep|offset|collect|enter)\b|"
    r"\blate (?:fee|charge)s?\b|\bpenalt(?:y|ies)\b|\binterest\b",
    re.I,
)
_CONDITIONAL = re.compile(
    r"\bif\b|\bunless\b|\bor\b|\botherwise\b|\bfail|\bnot\b|\bwithout\b", re.I
)
_ACTION = re.compile(
    r"\byou (?:must|need to|should|are (?:required|asked|expected|requested|directed|ordered|summoned|commanded|"
    r"instructed) to|will need to|have to|are to)\b|\bplease\b|\bbe sure to\b|\bmake sure\b|\bremember to\b|"
    r"\byou (?:will|may) (?:then |also )?be (?:required|asked|expected) to\b|\byou will (?:need to|have to|pay)\b|"
    r"\bdo not (?:eat|drink|take|forget|ignore|miss|bring|throw|delay|wait|leave|drive)\b|"
    r"\bdon't (?:eat|drink|forget|ignore|miss|wait)\b|\bit is (?:important|required|mandatory|necessary)\b|"
    r"\byou are (?:hereby )?(?:summoned|ordered|commanded|directed|required)\b|"
    r"\b(?:you|your \w+(?: \w+)?) (?:is|are) required\b",
    re.I,
)
_MUST = re.compile(r"\bmust\b", re.I)
_NOT_READER_MUST = re.compile(
    r"\b(?:we|the (?:court|landlord|owner|agency|office|company|plan|employer|department|collector|creditor))"
    r"(?:\s+\w+){0,2}\s*$",
    re.I,
)
_IMPERATIVE = re.compile(
    r"^(?:[^,]{2,110},\s*)?(?:then\s+|also\s+|please\s+)?"
    r"(?:call|return|send|mail|bring|submit|complete|sign|pay|contact|visit|go|appear|attend|report|provide|"
    r"fill (?:out|in)|read|keep|arrive|log (?:in|on)|respond|reply|answer|apply|request|schedule|reschedule|take|"
    r"stop|write|fax|upload|review|notify|tell|check|confirm|enclose|include|present|show|update|register|follow|"
    r"drink|eat|avoid|wear|cancel|make|have|remember|plan|print|detach|do not|don't|never|use|ask|let us know|"
    r"park|enter|gather|collect|begin|start|finish|continue|leave|wait|expect|allow|save|file|dispute|mark|"
    r"choose|select|list|attach|copy|photocopy|give|get|find|look|open|log|go|come|drive|arrange|bring)\b",
    re.I,
)
_SOFT_ACTION = re.compile(
    r"\byou (?:can|may) (?:also )?(?:pay|call|visit|go|mail|send|submit|apply|return|complete|reschedule|bring|use|"
    r"fax|upload|respond|reply|log in|sign|make|set up|enroll|update|drop off|file)\b",
    re.I,
)
_CONTACT_ONLY = re.compile(
    r"^(?:if you have (?:any )?questions|for (?:more )?(?:information|questions|help)|questions\?|"
    r"if you need (?:more )?(?:information|help)|please (?:do not hesitate|feel free) to|thank you|"
    r"(?:our )?(?:office|business) hours)",
    re.I,
)
_LEAD_LABEL = re.compile(
    r"^(?:[A-Z0-9][A-Z0-9 ,'/&()\-]{2,60}:\s*|(?i:step|part)\s*\d+\s*[:.)]\s*)"
)
_KEY_CUES: list[tuple[re.Pattern[str], float]] = [
    (
        re.compile(
            r"\bwe (?:have )?(?:decided|determined|denied|approved|reviewed|found|cancell?ed|reduced|increased|terminated|"
            r"selected|scheduled|received your|are (?:unable|denying|approving|cancell?ing|ending|stopping|reducing))\b",
            re.I,
        ),
        3.0,
    ),
    (
        re.compile(
            r"\b(?:has|have) been (?:denied|approved|scheduled|terminated|cancell?ed|reduced|increased|selected|filed|"
            r"referred|overpaid|assigned|placed|summoned|changed|updated|received)\b",
            re.I,
        ),
        3.0,
    ),
    (
        re.compile(
            r"\byou (?:owe|were overpaid|have been (?:selected|summoned|scheduled|approved|denied|overpaid)|are being sued|"
            r"are (?:hereby )?(?:summoned|required to appear)|received (?:benefits|payments) you)\b",
            re.I,
        ),
        4.0,
    ),
    (
        re.compile(
            r"\bthis (?:letter|notice) (?:is to|is about|explains|tells you|is your|confirms)\b|"
            r"\bthis is (?:a|an|your) (?:notice|reminder|summons|bill|final|statement|decision|confirmation)\b|"
            r"\bwe are writing (?:to|because|about)\b|\bthis is not a bill\b",
            re.I,
        ),
        3.0,
    ),
    (
        re.compile(
            r"\bpast due\b|\bfinal notice\b|\bnot a bill\b|\bnotice to (?:quit|vacate|pay)\b|\bdisconnect|\bshut ?off\b|"
            r"\bcancell?ation\b|\boverpayment\b|\bdenied\b|\bapproved\b|\bgarnish|\bevict|\bsued\b|\bsummons\b|\bjury\b|"
            r"\bbalance due\b|\bamount due\b|\bwill (?:change|increase|decrease|end|stop|be (?:cancell?ed|terminated|"
            r"reduced|increased))\b|\brenew|\bscheduled\b|\bconfirm",
            re.I,
        ),
        1.5,
    ),
    (re.compile(r"\$\s?\d", re.I), 1.0),
]
_SUBJECT_LINE = re.compile(r"^\s*(?:re|subject|regarding|notice of|important notice)\s*[:\-]", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:[-*•●▪–>]|\(?\d{1,2}[.)]|\(?[a-h][.)]|\[\s?\])\s+")


def _is_foreign(seg: Segment) -> bool:
    letters = [c for c in seg.text if c.isalpha()]
    if not letters:
        return False
    non_ascii = sum(not c.isascii() for c in letters) / len(letters)
    return non_ascii > 0.2 or len(_TAGLINE.findall(seg.text)) >= 2


def _units(segments: list[Segment], text: str) -> list[tuple[int, int, list[int]]]:
    """Group a list intro ("Please bring:") with its items into one unit."""
    units: list[tuple[int, int, list[int]]] = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if (
            seg.clean.endswith(":")
            and seg.words >= 3
            and not re.match(r"^(?:dear|to|re|attn|attention|hello|hi)\b", seg.clean, re.I)
        ):
            j = i + 1
            members = [i]
            while j < len(segments):
                nxt = segments[j]
                if nxt.block > segments[members[-1]].block + 1:
                    break
                is_item = bool(_LIST_ITEM.match(nxt.text)) or (
                    nxt.is_line and nxt.words <= 14 and not _SUBJECT_LINE.match(nxt.text)
                )
                if not is_item or nxt.clean.endswith(":"):
                    break
                members.append(j)
                j += 1
                if len(members) > 12:
                    break
            if len(members) > 1:
                units.append((seg.start, segments[members[-1]].end, members))
                i = j
                continue
        units.append((seg.start, seg.end, [i]))
        i += 1
    return units


def _lead(value: str) -> str:
    """A sentence without bullets and "STEP 1:" / "IF YOU DO NOTHING:" labels."""
    lead = _LIST_ITEM.sub("", collapse(value))
    for _ in range(2):
        lead = _LEAD_LABEL.sub("", lead).lstrip()
    return lead


def _reader_must(body: str) -> bool:
    for m in _MUST.finditer(body):
        if not _NOT_READER_MUST.search(body[max(0, m.start() - 40) : m.start()]):
            return True
    return False


def _classify_points(
    text: str, segments: list[Segment]
) -> tuple[list[FoundPoint], list[FoundPoint], list[FoundPoint], list[FoundPoint]]:
    actions: list[FoundPoint] = []
    consequences: list[FoundPoint] = []
    rights: list[FoundPoint] = []
    keys: list[FoundPoint] = []
    units = _units(segments, text)
    total = max(1, len(units))
    for position, (start, end, members) in enumerate(units):
        first = segments[members[0]]
        body = collapse(text[start:end])
        leads = [_lead(segments[m].text) for m in members]
        lead = leads[0]
        if _is_foreign(first) or len(body) < 12:
            continue
        boiler = bool(_BOILERPLATE.search(body))
        imperative = any(_IMPERATIVE.match(item) for item in leads)
        strong_action = bool(_ACTION.search(body) or _reader_must(body))
        strong_right = bool(_RIGHT_STRONG.search(body)) and not (
            _LOSE_RIGHT.search(body)
            and not re.search(r"\byou have the right\b|\bfree\b", body, re.I)
        )
        # Single address/letterhead lines are never actions.
        header_line = (
            first.is_line
            and len(members) == 1
            and not (
                imperative
                or strong_action
                or _LIST_ITEM.match(first.text)
                or (strong_right and first.words >= 6)
            )
        )
        parts = (
            [Span(segments[m].start, segments[m].end) for m in members] if len(members) > 1 else []
        )
        span = Span(start, end)
        is_action = strong_action or imperative or bool(_SOFT_ACTION.search(body))
        if _CONTACT_ONLY.match(lead) and not re.search(r"\bmust\b|\brequired\b", body, re.I):
            is_action = False
        disagree = bool(
            re.match(r"^if you (?:disagree|do not agree|don't agree|think)", lead, re.I)
        )
        consequence_start = bool(_CONSEQUENCE_START.match(lead)) and not disagree
        is_consequence = not disagree and (
            consequence_start
            or bool(_CONSEQUENCE_STRONG.search(body))
            or (bool(_CONSEQUENCE_WEAK.search(body)) and bool(_CONDITIONAL.search(body)))
        )
        weak_right = bool(_RIGHT_WEAK.search(body))
        explicit_right = bool(_EXPLICIT_RIGHT.search(body))
        if not header_line and not boiler:
            if consequence_start and explicit_right and not strong_action:
                rights.append(FoundPoint(span, "right", parts=parts))
            elif consequence_start and not strong_action:
                consequences.append(FoundPoint(span, "consequence", parts=parts))
            else:
                if is_action:
                    actions.append(FoundPoint(span, "action", parts=parts))
                if is_consequence:
                    consequences.append(FoundPoint(span, "consequence", parts=parts))
                if strong_right or (weak_right and not is_action and not is_consequence):
                    rights.append(FoundPoint(span, "right", parts=parts))
        # Key point scoring
        score = 0.0
        for pattern, weight in _KEY_CUES:
            if pattern.search(body):
                score += weight
        if _SUBJECT_LINE.match(first.text) and first.words >= 3:
            score += 3.5
        elif header_line:
            score -= 3
        if boiler or _is_foreign(first):
            score -= 6
        if len(body.split()) > 60:
            score -= 1.5
        score += 1.5 * (1 - position / total)
        if score >= 3:
            keys.append(FoundPoint(span, "key", score))
    keys.sort(key=lambda p: -p.score)
    chosen: list[FoundPoint] = []
    for k in keys:
        if all(k.quote.start != c.quote.start for c in chosen):
            chosen.append(k)
        if len(chosen) == 2:
            break
    chosen.sort(key=lambda p: p.quote.start)
    return actions, consequences, rights, chosen


# --------------------------------------------------------------------------- #
# Money, contacts, reference numbers
# --------------------------------------------------------------------------- #

_AMOUNT = re.compile(r"(?<![\w$])\$\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?(?![\d,]\d)")
_AMOUNT_CUES: dict[str, re.Pattern[str]] = {
    "overpayment": re.compile(r"\boverpa(?:id|yment)\b|\brepay\b|\bpay back\b", re.I),
    "benefit": re.compile(
        r"\bbenefits?\b|\bmonthly (?:amount|payment)\b|\ballotment\b|\byou will (?:receive|get)\b|"
        r"\bweekly benefit\b|\bnew (?:monthly )?amount\b|\bdeposit(?:ed)?\b|\bpension\b|\bannuity\b",
        re.I,
    ),
    "paid": re.compile(
        r"\b(?:plan|insurance|we|insurer) paid\b|\bpaid\b|\bcovered\b|\badjust(?:ment|ed)?\b|\bdiscounts?\b|"
        r"\bwrite[- ]?off\b|\bpayments? (?:received|applied)\b|\bcredits?\b|\ballowed\b|\bsaved?\b",
        re.I,
    ),
    "amount_due": re.compile(
        r"\b(?:amount|balance|total)(?: now)? due\b|\byou owe\b|\bowed?\b|\bpast[- ]due\b|\bbalance\b|\bpay\b|"
        r"\bsued\b|\bunpaid\b|\bjudgment\b|\bclaim(?:s|ing)?\b|\bgarnish\w*|\bcollect\w*|"
        r"\bsued\b|\bunpaid\b|\bjudgment\b|\bclaim(?:s|ing)?\b|\bgarnish\w*|\bcollect\w*|"
        r"\boutstanding\b|\bpatient responsibility\b|\byour (?:share|responsibility)\b|\btotal\b|\bminimum\b|\bdue\b",
        re.I,
    ),
    "charge": re.compile(
        r"\bcharges?\b|\bbilled\b|\bfees?\b|\bcosts?\b|\bpenalty\b|\binterest\b|\btax\b|\brent\b|\bpremium\b|"
        r"\bfines?\b|\bdeductible\b|\bcopay\b",
        re.I,
    ),
}


def _amount_kind(line: str, pos: int, end: int) -> str:
    best, best_dist = "other", 1e9
    for kind, pattern in _AMOUNT_CUES.items():
        for m in pattern.finditer(line):
            if m.end() <= pos:
                gap = line[m.end() : pos]
                dist = float(len(gap))
            elif m.start() >= end:
                gap = line[end : m.start()]
                dist = len(gap) * 1.6
            else:
                continue
            if re.search(r"\$\s?\d", gap):
                dist += 40
            if dist < best_dist:
                best, best_dist = kind, dist
    return best if best_dist < 80 else "other"


def _find_amounts(text: str, segments: list[Segment]) -> list[FoundAmount]:
    out: list[FoundAmount] = []
    seen: set[float] = set()
    for m in _AMOUNT.finditer(text):
        raw = m.group(0)
        value = float(raw.replace("$", "").replace(",", "").strip())
        if value in seen:
            continue
        seen.add(value)
        idx = _segment_index(segments, m.start())
        seg = segments[idx] if idx is not None else None
        if seg is None:
            continue
        local = m.start() - seg.start
        kind = _amount_kind(seg.text, local, local + len(raw))
        display = raw.replace(" ", "")
        out.append(FoundAmount(value, display, kind, Span(seg.start, seg.end)))
    return out


_PHONE = re.compile(
    r"(?<![\w\-/.])(?:\+?1[\s.\-]?)?(?:\(\d{3}\)\s*|\d{3}[\s.\-])\d{3}[\s.\-]\d{4}(?![\w\-/])"
    r"|(?<![\w\-/.])1[\s.\-]?8\d\d[\s.\-]\d{3}[\s.\-]\d{4}(?![\w\-/])"
)
_PHONE7 = re.compile(r"(?<![\w\-/.()])\d{3}-\d{4}(?![\w\-/])")
_PHONE_CONTEXT = re.compile(
    r"\b(?:call|phone|tel|telephone|fax|tty|tdd|line|number|dial|contact|text)\b", re.I
)
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
_WEB = re.compile(
    r"\b(?:https?://)?(?:www\.)?(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|org|net|gov|edu|us|info|io|co|biz|health|law|example|test|care|app|online|site|ca|uk)\b"
    r"(?:/[^\s,;)\"'<>]*)?",
    re.I,
)
_TTY_CUE = re.compile(
    r"\btty\b|\btdd\b|\btext telephone\b|\brelay\b|\bdeaf\b|\bhard of hearing\b|\bhearing[- ]impaired\b",
    re.I,
)
_FAX_CUE = re.compile(r"\bfax\b|\bfacsimile\b", re.I)


def _contact_kind(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    before = text[max(line_start, start - 40) : start]
    # The closest label wins: "Phone: 555-0100  Fax: 555-0101".
    best, best_pos = "phone", -1
    for kind, pattern in (
        ("tty", _TTY_CUE),
        ("fax", _FAX_CUE),
        ("phone", re.compile(r"\b(?:phone|call|tel|telephone)\b", re.I)),
    ):
        for m in pattern.finditer(before):
            if m.start() > best_pos:
                best, best_pos = kind, m.start()
    return best


def _find_contacts(text: str, segments: list[Segment]) -> list[FoundContact]:
    out: list[FoundContact] = []
    seen: set[str] = set()
    taken: list[tuple[int, int]] = []

    def add(kind: str, value: str, normalized: str, start: int, end: int) -> None:
        taken.append((start, end))
        if normalized in seen:
            return
        seen.add(normalized)
        idx = _segment_index(segments, start)
        seg = segments[idx] if idx is not None else None
        span = Span(seg.start, seg.end) if seg else Span(start, end)
        out.append(FoundContact(kind, value, normalized, span))

    for m in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            continue
        add(_contact_kind(text, m.start()), m.group(0).strip(), digits, m.start(), m.end())
    for m in _PHONE7.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        context = text[max(0, m.start() - 50) : m.start()]
        if not _PHONE_CONTEXT.search(context):
            continue
        digits = re.sub(r"\D", "", m.group(0))
        add(_contact_kind(text, m.start()), m.group(0), digits, m.start(), m.end())
    for m in re.finditer(r"\b711\b", text):
        if _TTY_CUE.search(text[max(0, m.start() - 40) : m.end() + 20]):
            add("tty", "711", "711", m.start(), m.end())
    email_spans: list[tuple[int, int]] = []
    for m in _EMAIL.finditer(text):
        value = m.group(0).rstrip(".")
        email_spans.append((m.start(), m.end()))
        add("email", value, value.lower(), m.start(), m.end())
    for m in _WEB.finditer(text):
        if any(s <= m.start() < e for s, e in email_spans):
            continue
        value = m.group(0).rstrip(".:)")
        if "@" in text[max(0, m.start() - 1) : m.start()]:
            continue
        normalized = (
            re.sub(r"^(?:https?://)?(?:w{3,4}\.)?", "", value, flags=re.I).lower().rstrip("/")
        )
        if "." not in normalized or re.fullmatch(r"[\d.]+", normalized):
            continue
        add("website", value, normalized, m.start(), m.end())
    return out


_REF = re.compile(
    r"\b(?P<label>case|claim(?:ant)?|account|acct\.?|member|participant|subscriber|notice|reference|ref\.?|invoice|"
    r"bill|statement|receipt|confirmation|tracking|policy|client|applicant|customer|patient|docket|file|citation|"
    r"ticket|loan|certificate|record|student|tax ?payer|household|recipient|beneficiary|employer|unit|"
    r"application|appeal|request|cause|petition|order|identification|group|determination|garnishment|writ|"
    r"license|plate|permit|registration|enrollment|authorization|reference|estimate|encounter|visit|"
    r"parcel|apn|service request|work order|employee|badge)"
    r"(?P<qual>(?:\s+(?:id|identification|number|no\.?|num\.?|#|code))*(?:\s*\([A-Z]{2,6}\))?)\s*"
    r"(?P<sep>[#:]|-\s)?\s*"
    r"(?P<value>(?=[A-Za-z0-9\-/]*\d)[A-Za-z0-9][A-Za-z0-9\-/]{2,}[A-Za-z0-9])(?![\w-])",
    re.I,
)
_REF_ID = re.compile(
    r"\b(?P<label>ID)(?P<qual>\s*(?:number|no\.?|#))?\s*(?P<sep>[#:])?\s*(?P<value>[A-Za-z0-9][A-Za-z0-9\-]{3,}[A-Za-z0-9])\b"
)
_REF_KINDS = {
    "case": "case",
    "docket": "case",
    "file": "case",
    "cause": "case",
    "citation": "case",
    "ticket": "case",
    "petition": "case",
    "order": "reference",
    "claim": "claim",
    "claimant": "claim",
    "account": "account",
    "acct": "account",
    "loan": "account",
    "patient": "account",
    "customer": "account",
    "member": "member",
    "participant": "member",
    "subscriber": "member",
    "beneficiary": "member",
    "recipient": "member",
    "notice": "notice",
    "letter": "notice",
    "reference": "reference",
    "ref": "reference",
    "invoice": "invoice",
    "bill": "invoice",
    "statement": "invoice",
    "receipt": "receipt",
    "confirmation": "receipt",
    "tracking": "receipt",
    "application": "receipt",
    "appeal": "reference",
    "request": "reference",
    "policy": "policy",
    "client": "client",
    "applicant": "client",
    "student": "client",
    "taxpayer": "client",
    "tax payer": "client",
    "household": "client",
    "employer": "client",
    "unit": "reference",
    "certificate": "reference",
    "record": "reference",
    "id": "client",
    "identification": "client",
    "group": "policy",
    "determination": "notice",
    "garnishment": "case",
    "writ": "case",
    "license": "reference",
    "plate": "reference",
    "permit": "reference",
    "registration": "reference",
    "enrollment": "member",
    "authorization": "reference",
    "estimate": "reference",
    "encounter": "account",
    "visit": "account",
    "parcel": "account",
    "apn": "account",
    "service request": "reference",
    "work order": "reference",
    "employee": "client",
    "badge": "client",
}


def _find_references(
    text: str, segments: list[Segment], tables: list[TableField] | None = None
) -> list[FoundReference]:
    out: list[FoundReference] = []
    seen: set[str] = set()
    for cell in tables or []:
        label_m = _REF.match(cell.label + ": X1X1")
        value = text[cell.start : cell.end]
        if not label_m or not re.search(r"\d", value) or " " in value.strip() or len(value) < 4:
            continue
        if re.fullmatch(r"[0-3]?\d[/\-.][0-3]?\d[/\-.]\d{2,4}", value):
            continue
        seen.add(value)
        idx = _segment_index(segments, cell.start)
        seg = segments[idx] if idx is not None else None
        span = Span(seg.start, seg.end) if seg else Span(cell.start, cell.end)
        label = label_m["label"].lower().rstrip(".")
        out.append(FoundReference(_REF_KINDS.get(label, "reference"), value, span))
    for pattern in (_REF, _REF_ID):
        for m in pattern.finditer(text):
            if not (m["qual"] or m["sep"]):
                continue
            value = m["value"]
            if not re.search(r"\d", value) or len(re.sub(r"\D", "", value)) < 3:
                continue
            if re.fullmatch(
                r"[0-3]?\d[/\-.][0-3]?\d[/\-.]\d{2,4}|(?:19|20)\d{2}-\d{2}-\d{2}", value
            ):
                continue
            if re.fullmatch(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]\d{4}|\d{3}-\d{4}", value):
                continue
            if value.lower().endswith(("am", "pm")) and re.fullmatch(
                r"\d{1,2}(?::\d{2})?(?:am|pm)", value.lower()
            ):
                continue
            if value in seen:
                continue
            label = m["label"].lower().rstrip(".").replace("  ", " ")
            seen.add(value)
            idx = _segment_index(segments, m.start("value"))
            seg = segments[idx] if idx is not None else None
            span = Span(seg.start, seg.end) if seg else Span(m.start(), m.end())
            out.append(FoundReference(_REF_KINDS.get(label, "reference"), value, span))
    out.sort(key=lambda r: r.quote.start)
    return out


# --------------------------------------------------------------------------- #
# Glossary
# --------------------------------------------------------------------------- #


@cache
def _glossary() -> list[tuple[re.Pattern[str], dict[str, object]]]:
    raw = (resources.files("plainread") / "data" / "glossary.json").read_text(encoding="utf-8")
    entries: list[dict[str, object]] = json.loads(raw)
    compiled = []
    for entry in entries:
        names = [str(entry["term"]), *[str(a) for a in entry.get("aliases", [])]]  # type: ignore[attr-defined]
        names.sort(key=len, reverse=True)
        flags = 0 if str(entry["term"]).isupper() else re.I
        pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", flags)
        compiled.append((pattern, entry))
    return compiled


def find_terms(
    text: str, segments: list[Segment], letter_type: str, limit: int = 12
) -> list[FoundTerm]:
    candidates: list[tuple[list[tuple[int, int]], dict[str, object]]] = []
    for pattern, entry in _glossary():
        types = entry.get("types")
        if isinstance(types, list) and letter_type not in types:
            continue
        spans = [(m.start(), m.end()) for m in pattern.finditer(text)]
        if spans:
            candidates.append((spans, entry))
    hits: list[tuple[int, FoundTerm]] = []
    for spans, entry in candidates:
        # Skip "judgment" when every mention is part of "default judgment".
        others = [o for o_spans, other in candidates if other is not entry for o in o_spans]
        free = [
            (s, e)
            for s, e in spans
            if not any(os <= s and e <= oe and (oe - os) > (e - s) for os, oe in others)
        ]
        if not free:
            continue
        start = free[0][0]
        idx = _segment_index(segments, start)
        seg = segments[idx] if idx is not None else None
        if seg is None or _is_foreign(seg):
            continue
        meanings = {k: str(v) for k, v in entry.items() if k not in ("term", "aliases", "types")}
        shown = text[free[0][0] : free[0][1]]
        if not str(entry["term"]).isupper():
            shown = shown.lower()
        hits.append((start, FoundTerm(shown, meanings, Span(seg.start, seg.end))))
    hits.sort(key=lambda h: h[0])
    return [h[1] for h in hits[:limit]]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def extract(
    text: str,
    segments: list[Segment],
    today: dt.date,
    date_order: DateOrder = "MDY",
) -> Findings:
    found = d.find_dates(text, date_order)
    tables = table_fields(text)
    letter_date, letter_span = _find_letter_date(text, segments, found, today, tables)
    dates_found = _find_dates(text, segments, found, letter_date, letter_span, today, tables)
    actions, consequences, rights, keys = _classify_points(text, segments)
    return Findings(
        letter_date=letter_date,
        letter_date_span=letter_span,
        dates=dates_found,
        actions=actions,
        consequences=consequences,
        rights=rights,
        key_points=keys,
        amounts=_find_amounts(text, segments),
        contacts=_find_contacts(text, segments),
        references=_find_references(text, segments, tables),
    )
