#!/usr/bin/env python3
"""Turn ``plainread eval --json`` reports into a Markdown table (for CI summaries).

python scripts/eval_summary.py eval-text.json eval-ocr.json >> "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROWS = [
    ("dates_f1", "Important dates (F1)"),
    ("date_kind_accuracy", "Date type correct"),
    ("amounts_f1", "Money amounts (F1)"),
    ("phones_f1", "Phone numbers (F1)"),
    ("emails_f1", "Emails (F1)"),
    ("websites_f1", "Websites (F1)"),
    ("references_f1", "Case/account numbers (F1)"),
    ("actions_recall", "Things to do (recall)"),
    ("consequences_recall", "Consequences (recall)"),
    ("rights_recall", "Rights and help (recall)"),
    ("letter_type_accuracy", "Letter type"),
    ("letter_date_accuracy", "Letter date"),
    ("grounding", "Quotes found in letter"),
]


def main() -> None:
    reports = [(Path(p).stem, json.loads(Path(p).read_text("utf-8"))) for p in sys.argv[1:]]
    if not reports:
        sys.exit(__doc__)
    header = (
        "| Metric | " + " | ".join(f"{name} ({r['letters']} letters)" for name, r in reports) + " |"
    )
    print("### Plainread quality report\n")
    print(header)
    print("|---|" + "---:|" * len(reports))
    for key, label in ROWS:
        cells = []
        for _, report in reports:
            value = report["metrics"].get(key)
            need = report["thresholds"].get(key)
            mark = (
                ""
                if need is None
                else (" ✅" if value is not None and value + 1e-9 >= need else " ❌")
            )
            cells.append("–" if value is None else f"{value:.1%}{mark}")
        print(f"| {label} | " + " | ".join(cells) + " |")
    for name, report in reports:
        if report["failures"]:
            print(f"\n**{name}: below threshold** — " + "; ".join(report["failures"]))


if __name__ == "__main__":
    main()
