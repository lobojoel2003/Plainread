"""Command-line interface: ``plainread serve | explain | eval | doctor | languages``."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from plainread import i18n, llm, ocr
from plainread.config import Settings
from plainread.ics import build_calendar
from plainread.models import Explanation, Point
from plainread.pipeline import Upload, explain_text, explain_uploads
from plainread.version import version_string

URGENCY_STYLE = {
    "overdue": "bold white on red",
    "today": "bold white on red",
    "urgent": "bold red",
    "soon": "bold yellow",
    "later": "green",
}


def _quote(text: str) -> Text:
    return Text("“" + " ".join(text.split()) + "”", style="italic dim")


def _points(title: str, points: list[Point]) -> Panel | None:
    if not points:
        return None
    body = Text()
    for i, p in enumerate(points):
        if i:
            body.append("\n\n")
        body.append("• ", style="bold")
        body.append(p.text)
        if " ".join(p.text.split()).lower() != " ".join(p.quote.text.split()).lower():
            body.append("\n  ")
            body.append_text(_quote(p.quote.text))
    return Panel(body, title=f"[bold]{title}", title_align="left", border_style="cyan")


def render(e: Explanation, console: Console) -> None:
    lang = e.language
    head = Text()
    for line in e.summary:
        head.append(line + "\n")
    for p in e.key_points:
        head.append("\n" + i18n.t(lang, "summary.key_point") + " ", style="bold")
        head.append(p.text)
    console.print(
        Panel(
            head,
            title=f"[bold]{i18n.t(lang, 'sections.what_is_this')}",
            title_align="left",
            border_style="bright_blue",
        )
    )
    if e.dates:
        table = Table(title=None, expand=True, show_lines=True, border_style="magenta")
        table.add_column(i18n.t(lang, "sections.important_dates"), style="bold", ratio=2)
        table.add_column("", ratio=1)
        table.add_column(i18n.t(lang, "ui.letter_says"), ratio=4)
        for d in e.dates:
            rel = i18n.relative_day(d.days_left or 0, lang)
            when = Text(d.date_text + "\n")
            when.append(f"{d.label} · {rel}", style=URGENCY_STYLE.get(d.urgency or "later", ""))
            note = Text(d.description)
            if d.note:
                note.append("\n" + d.note, style="yellow")
            same = " ".join(d.description.split()).lower() == " ".join(d.quote.text.split()).lower()
            cell = (
                Group(_quote(d.quote.text))
                if same and not d.note
                else Group(note, _quote(d.quote.text))
            )
            table.add_row(when, i18n.t(lang, f"urgency.{d.urgency}"), cell)
        console.print(table)
    for title, items in (
        ("what_to_do", e.actions),
        ("consequences", e.consequences),
        ("rights", e.rights),
    ):
        panel = _points(i18n.t(lang, f"sections.{title}"), items)
        if panel:
            console.print(panel)
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="bold")
    facts.add_column()
    for a in e.amounts:
        facts.add_row(a.label, a.display)
    for c in e.contacts:
        facts.add_row(c.label, c.value)
    for r in e.references:
        facts.add_row(r.label, r.value)
    if facts.row_count:
        console.print(
            Panel(
                facts,
                title=f"[bold]{i18n.t(lang, 'sections.money')} · "
                f"{i18n.t(lang, 'sections.contacts')} · {i18n.t(lang, 'sections.numbers')}",
                title_align="left",
                border_style="green",
            )
        )
    if e.glossary:
        words = Table.grid(padding=(0, 2))
        words.add_column(style="bold")
        words.add_column()
        for g in e.glossary:
            words.add_row(g.term, g.meaning)
        console.print(
            Panel(
                words,
                title=f"[bold]{i18n.t(lang, 'sections.words')}",
                title_align="left",
                border_style="white",
            )
        )
    notes = [*e.warnings]
    if e.reading_level_text:
        notes.insert(0, e.reading_level_text)
    notes.append(e.disclaimer)
    console.print(Text("\n".join("! " + n for n in notes), style="yellow"))
    engine = (
        i18n.t(lang, "ui.engine_rules")
        if e.engine == "rules"
        else i18n.t(lang, "ui.engine_ai", model=e.engine.split(":", 2)[-1])
    )
    console.print(Text(engine, style="dim"))


def _model(settings: Settings, wanted: bool) -> llm.LocalModel | None:
    if not wanted:
        return None
    try:
        model = llm.from_settings(settings)
    except llm.RemoteAIRefusedError as exc:
        print(f"plainread: {exc}", file=sys.stderr)
        return None
    if model is None or not model.available():
        print(
            f"plainread: local AI model '{settings.model}' is not available at {settings.ai_url}; "
            "using the basic explainer.",
            file=sys.stderr,
        )
        return None
    return model


def cmd_explain(args: argparse.Namespace) -> int:
    settings = Settings()
    if args.model:
        settings.model = args.model
    today = dt.date.fromisoformat(args.today) if args.today else None
    kwargs = {
        "language": args.lang,
        "today": today,
        "date_order": args.date_order or settings.date_order,
        "ai": _model(settings, args.ai),
    }
    try:
        if args.files == ["-"]:
            e = explain_text(sys.stdin.read(), **kwargs)
        else:
            uploads = []
            for name in args.files:
                path = Path(name)
                if not path.is_file():
                    print(f"plainread: no such file: {name}", file=sys.stderr)
                    return 2
                uploads.append(Upload(path.read_bytes(), path.name))
            e = explain_uploads(uploads, ocr_lang=args.ocr_lang or settings.ocr_lang, **kwargs)
    except ocr.OcrUnavailableError:
        print(
            "plainread: Tesseract OCR is not installed. Run `plainread doctor` for help.",
            file=sys.stderr,
        )
        return 3
    except ocr.UnsupportedFileError as exc:
        print(f"plainread: {exc}", file=sys.stderr)
        return 2
    if args.ics:
        Path(args.ics).write_text(build_calendar(e.dates, e.sender), encoding="utf-8")
    if args.json:
        exclude = None if args.include_text else {"source_text"}
        print(json.dumps(e.model_dump(mode="json", exclude=exclude), ensure_ascii=False, indent=2))
    else:
        render(e, Console(width=args.width) if args.width else Console())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from plainread.api import create_app

    settings = Settings()
    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"  # noqa: S104
    print(f"Plainread {version_string()} is running at {url}")
    print("Your letters stay on this computer. Press Ctrl+C to stop.")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("Note: other devices on your network can reach this server.")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host=host, port=port, log_level=args.log_level)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from plainread.evaluation import THRESHOLDS, evaluate

    folder = Path(args.letters)
    if not folder.is_dir():
        print(f"plainread: letters folder not found: {folder}", file=sys.stderr)
        return 2
    if args.ocr and not ocr.ocr_available():
        print("plainread: --ocr needs Tesseract installed.", file=sys.stderr)
        return 3
    report = evaluate(folder, ocr=args.ocr)
    console = Console()
    metrics = report.metrics()
    table = Table(title=f"Plainread evaluation ({report.mode} mode, {report.letters} letters)")
    table.add_column("Metric")
    table.add_column("Score", justify="right")
    table.add_column("Needs", justify="right")
    table.add_column("")
    shown = sorted(
        set(THRESHOLDS[report.mode]) | {k for k in metrics if k.endswith(("_precision", "_recall"))}
    )
    for name in shown:
        value = metrics.get(name)
        if value is None:
            continue
        need = THRESHOLDS[report.mode].get(name)
        ok = need is None or value + 1e-9 >= need
        table.add_row(
            name,
            f"{value:.3f}",
            f"{need:.2f}" if need is not None else "",
            "[green]✓" if ok else "[red]✗",
        )
    console.print(table)
    if args.details:
        for result in report.results:
            if result.problems:
                console.print(f"[bold]{result.id}[/] ({result.seconds}s)")
                for problem in result.problems:
                    console.print(f"  - {problem}")
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    failures = report.failures()
    if failures:
        console.print("[red]Below threshold:[/] " + "; ".join(failures))
        return 0 if args.no_fail else 1
    console.print(f"[green]All quality thresholds met[/] in {report.seconds:.1f}s.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = Settings()
    console = Console()
    console.print(f"[bold]Plainread[/] {version_string()}")
    tess = ocr.tesseract_version()
    if tess:
        console.print(f"[green]✓[/] Photo reading: Tesseract {tess} ({ocr.tesseract_command()})")
    else:
        console.print(
            "[yellow]![/] Photo reading: Tesseract is not installed. Pasting text still works."
        )
        console.print("    Windows: https://github.com/UB-Mannheim/tesseract/wiki")
        console.print("    macOS:   brew install tesseract")
        console.print("    Linux:   sudo apt install tesseract-ocr")
    try:
        model = llm.from_settings(settings)
    except llm.RemoteAIRefusedError as exc:
        console.print(f"[red]✗[/] Local AI: {exc}")
        return 1
    if model is None:
        console.print("[dim]-[/] Local AI: turned off (PLAINREAD_AI=off)")
    elif model.available():
        console.print(
            f"[green]✓[/] Local AI: {settings.model} via {settings.ai_backend} at {settings.ai_url}"
        )
    else:
        console.print(
            f"[yellow]![/] Local AI: '{settings.model}' not found at {settings.ai_url} (optional)."
        )
        console.print("    Install Ollama from https://ollama.com, then run:")
        console.print(f"    ollama pull {settings.model}")
    return 0


def cmd_languages(args: argparse.Namespace) -> int:
    for lang in i18n.languages():
        print(f"{lang['code']:4} {lang['name']:24} {lang['native_name']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plainread",
        description="Explain hard letters in plain language, privately, on your own device.",
    )
    parser.add_argument("--version", action="version", version=f"plainread {version_string()}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="start the web app (default when no command is given)")
    serve.add_argument(
        "--host", help="address to listen on (default 127.0.0.1, this computer only)"
    )
    serve.add_argument("--port", type=int, help="port to listen on (default 8765)")
    serve.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    serve.add_argument(
        "--log-level", default="warning", choices=["critical", "error", "warning", "info", "debug"]
    )
    serve.set_defaults(func=cmd_serve)

    explain = sub.add_parser(
        "explain", help="explain a letter (photo, PDF or text file; '-' reads stdin)"
    )
    explain.add_argument("files", nargs="+", help="one or more pages: .jpg .png .pdf .txt, or '-'")
    explain.add_argument(
        "--lang", "-l", default="en", help="language for the results (see `plainread languages`)"
    )
    explain.add_argument(
        "--ai",
        action="store_true",
        help="use the local AI model for plainer wording and translation",
    )
    explain.add_argument("--model", help="local model name (default: PLAINREAD_MODEL or gemma3:4b)")
    explain.add_argument(
        "--json", action="store_true", help="print JSON instead of a formatted report"
    )
    explain.add_argument(
        "--include-text", action="store_true", help="include the letter text in --json output"
    )
    explain.add_argument("--ics", metavar="FILE", help="also save the dates as a calendar file")
    explain.add_argument("--today", metavar="YYYY-MM-DD", help="pretend today is this date")
    explain.add_argument(
        "--date-order", choices=["MDY", "DMY"], help="how to read dates like 03/04/2026"
    )
    explain.add_argument("--ocr-lang", help="Tesseract language code(s), e.g. eng or eng+spa")
    explain.add_argument("--width", type=int, help="output width in characters")
    explain.set_defaults(func=cmd_explain)

    ev = sub.add_parser("eval", help="score Plainread against the labelled sample letters")
    ev.add_argument(
        "--letters", default="eval/letters", help="folder of <id>.txt + <id>.json letters"
    )
    ev.add_argument(
        "--ocr", action="store_true", help="render each letter as a photo and OCR it first"
    )
    ev.add_argument("--json", metavar="FILE", help="write the full report as JSON")
    ev.add_argument("--details", action="store_true", help="list every miss and false alarm")
    ev.add_argument("--no-fail", action="store_true", help="exit 0 even when below thresholds")
    ev.set_defaults(func=cmd_eval)

    doctor = sub.add_parser("doctor", help="check that OCR and local AI are set up")
    doctor.set_defaults(func=cmd_doctor)

    langs = sub.add_parser("languages", help="list supported languages")
    langs.set_defaults(func=cmd_languages)
    return parser


def _utf8_output() -> None:
    """Make piped output UTF-8 on Windows, where pipes default to a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            with contextlib.suppress(OSError, ValueError):
                stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["serve", *(argv or [])])
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
