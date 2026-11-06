"""Score Plainread against the hand-labelled sample letters in ``eval/letters``.

See ``eval/README.md`` for the answer format and how each field is scored.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from plainread.grounding import grounding_rate
from plainread.models import Explanation
from plainread.pipeline import Upload, explain_text, explain_uploads

SET_FIELDS = ("dates", "amounts", "phones", "emails", "websites", "references")
KEYWORD_FIELDS = ("actions", "consequences", "rights")

# Minimum scores CI enforces. OCR mode allows a little slack for reading errors.
THRESHOLDS: dict[str, dict[str, float]] = {
    "text": {
        "dates_f1": 0.90,
        "amounts_f1": 0.95,
        "phones_f1": 0.95,
        "emails_f1": 0.95,
        "websites_f1": 0.90,
        "references_f1": 0.85,
        "date_kind_accuracy": 0.80,
        "actions_recall": 0.80,
        "consequences_recall": 0.70,
        "rights_recall": 0.70,
        "letter_type_accuracy": 0.85,
        "letter_date_accuracy": 0.90,
        "grounding": 1.0,
    },
    "ocr": {
        "dates_f1": 0.85,
        "amounts_f1": 0.90,
        "phones_f1": 0.90,
        "emails_f1": 0.85,
        "websites_f1": 0.80,
        "references_f1": 0.75,
        "date_kind_accuracy": 0.75,
        "actions_recall": 0.75,
        "consequences_recall": 0.65,
        "rights_recall": 0.65,
        "letter_type_accuracy": 0.80,
        "letter_date_accuracy": 0.85,
        "grounding": 1.0,
    },
}


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class LetterResult:
    id: str
    problems: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class Report:
    mode: str
    letters: int
    counts: dict[str, Counts]
    recall: dict[str, tuple[int, int]]
    accuracy: dict[str, tuple[int, int]]
    grounding: float
    results: list[LetterResult]
    seconds: float

    def metrics(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, c in self.counts.items():
            out[f"{name}_precision"] = round(c.precision, 4)
            out[f"{name}_recall"] = round(c.recall, 4)
            out[f"{name}_f1"] = round(c.f1, 4)
        for name, (hit, total) in self.recall.items():
            out[f"{name}_recall"] = round(hit / total, 4) if total else 1.0
        for name, (hit, total) in self.accuracy.items():
            out[f"{name}_accuracy"] = round(hit / total, 4) if total else 1.0
        out["grounding"] = round(self.grounding, 4)
        return out

    def failures(self) -> list[str]:
        metrics = self.metrics()
        return [
            f"{name} = {metrics.get(name, 0):.3f} (needs {minimum:.2f})"
            for name, minimum in THRESHOLDS[self.mode].items()
            if metrics.get(name, 0) + 1e-9 < minimum
        ]

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "letters": self.letters,
            "seconds": round(self.seconds, 2),
            "metrics": self.metrics(),
            "thresholds": THRESHOLDS[self.mode],
            "failures": self.failures(),
            "results": [asdict(r) for r in self.results],
        }


def _norm_web(value: str) -> str:
    value = re.sub(r"^(?:https?://)?(?:www\.)?", "", value.strip().lower())
    return value.rstrip("/.")


def predicted_sets(e: Explanation) -> dict[str, set[str]]:
    return {
        "dates": {d.date.isoformat() for d in e.dates},
        "amounts": {f"{a.value:.2f}" for a in e.amounts},
        "phones": {c.normalized for c in e.contacts if c.kind in ("phone", "tty", "fax")},
        "emails": {c.normalized for c in e.contacts if c.kind == "email"},
        "websites": {_norm_web(c.normalized) for c in e.contacts if c.kind == "website"},
        "references": {r.value.upper() for r in e.references},
    }


def gold_sets(gold: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "dates": {str(x["date"]) for x in gold.get("dates", [])},
        "amounts": {f"{float(x):.2f}" for x in gold.get("amounts", [])},
        "phones": {re.sub(r"\D", "", str(x)) for x in gold.get("phones", [])},
        "emails": {str(x).lower() for x in gold.get("emails", [])},
        "websites": {_norm_web(str(x)) for x in gold.get("websites", [])},
        "references": {str(x).upper() for x in gold.get("references", [])},
    }


def _contains_all(quote: str, keywords: list[str]) -> bool:
    haystack = re.sub(r"\s+", " ", quote).lower()
    return all(k.lower() in haystack for k in keywords)


def load_letters(folder: Path) -> list[tuple[str, str, dict[str, Any]]]:
    letters = []
    for answer in sorted(folder.glob("*.json")):
        text_file = answer.with_suffix(".txt")
        if text_file.exists():
            gold = json.loads(answer.read_text("utf-8"))
            letters.append((answer.stem, text_file.read_text("utf-8"), gold))
    return letters


def evaluate(folder: Path, ocr: bool = False) -> Report:
    started = time.perf_counter()
    counts = {name: Counts() for name in SET_FIELDS}
    recall = dict.fromkeys(KEYWORD_FIELDS, (0, 0))
    accuracy = {"letter_type": (0, 0), "letter_date": (0, 0), "sender": (0, 0), "date_kind": (0, 0)}
    total_quotes = 0
    good_quotes = 0.0
    results: list[LetterResult] = []
    letters = load_letters(folder)
    for letter_id, text, gold in letters:
        t0 = time.perf_counter()
        today = dt.date.fromisoformat(gold["today"])
        if ocr:
            from plainread.synth import render_letter

            image = render_letter(text, photo=True, seed=sum(map(ord, letter_id)))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
            e = explain_uploads(
                [Upload(buffer.getvalue(), f"{letter_id}.jpg", "image/jpeg")], today=today
            )
        else:
            e = explain_text(text, today=today)
        result = LetterResult(letter_id)
        predicted, expected = predicted_sets(e), gold_sets(gold)
        for name in SET_FIELDS:
            p, g = predicted[name], expected[name]
            c = counts[name]
            c.tp += len(p & g)
            c.fp += len(p - g)
            c.fn += len(g - p)
            for missing in sorted(g - p):
                result.problems.append(f"{name}: missed {missing}")
            for extra in sorted(p - g):
                result.problems.append(f"{name}: extra {extra}")
        # Date kinds, for the dates we did find.
        hit, total = accuracy["date_kind"]
        for gd in gold.get("dates", []):
            mine = [d for d in e.dates if d.date.isoformat() == gd["date"]]
            if not mine:
                continue
            total += 1
            if any(d.kind == gd["kind"] for d in mine):
                hit += 1
            else:
                result.problems.append(
                    f"date kind: {gd['date']} is {gd['kind']}, got {','.join(d.kind for d in mine)}"
                )
        accuracy["date_kind"] = (hit, total)
        for name in KEYWORD_FIELDS:
            points = getattr(e, name)
            hit, total = recall[name]
            for keywords in gold.get(name, []):
                total += 1
                if any(_contains_all(p.quote.text, keywords) for p in points):
                    hit += 1
                else:
                    result.problems.append(f"{name}: missed {keywords}")
            recall[name] = (hit, total)

        def score(key: str, ok: bool, detail: str, result: LetterResult = result) -> None:
            h, t = accuracy[key]
            accuracy[key] = (h + int(ok), t + 1)
            if not ok:
                result.problems.append(detail)

        score(
            "letter_type",
            e.letter_type == gold["letter_type"],
            f"letter type: expected {gold['letter_type']}, got {e.letter_type}",
        )
        expected_date = gold.get("letter_date")
        got_date = e.letter_date.isoformat() if e.letter_date else None
        score(
            "letter_date",
            got_date == expected_date,
            f"letter date: expected {expected_date}, got {got_date}",
        )
        if gold.get("sender"):
            ok = bool(e.sender and gold["sender"].lower() in e.sender.lower())
            score("sender", ok, f"sender: expected '{gold['sender']}', got '{e.sender}'")
        quotes = e.all_quotes()
        total_quotes += len(quotes)
        good_quotes += grounding_rate(e) * len(quotes)
        result.seconds = round(time.perf_counter() - t0, 3)
        results.append(result)
    return Report(
        mode="ocr" if ocr else "text",
        letters=len(letters),
        counts=counts,
        recall=recall,
        accuracy=accuracy,
        grounding=(good_quotes / total_quotes) if total_quotes else 1.0,
        results=results,
        seconds=time.perf_counter() - started,
    )
