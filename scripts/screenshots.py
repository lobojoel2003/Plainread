#!/usr/bin/env python3
"""Regenerate the images in docs/images/ used by the README.

    pip install -e ".[e2e]" && playwright install chromium
    python scripts/screenshots.py --today 2026-11-06

Uses only the fictional sample letters bundled with Plainread.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import socket
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server() -> str:
    import uvicorn

    from plainread.api import create_app
    from plainread.config import Settings

    settings = Settings()
    settings.ai = "off"
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"


def letter_photo(today: dt.date) -> Path:
    from plainread.samples import get_sample
    from plainread.synth import render_letter

    text = get_sample("benefits-renewal", today)["text"]
    image = render_letter(text, photo=True, seed=11)
    image.thumbnail((1100, 1600))
    path = OUT / "letter-photo.jpg"
    image.save(path, format="JPEG", quality=82, optimize=True)
    return path


def cli_svg(today: dt.date) -> None:
    from rich.console import Console

    from plainread.cli import render
    from plainread.pipeline import explain_text
    from plainread.samples import get_sample

    text = get_sample("utility-shutoff", today)["text"]
    explanation = explain_text(text, today=today)
    explanation.glossary = explanation.glossary[:4]
    console = Console(
        record=True, width=104, file=io.StringIO(), force_terminal=True, color_system="truecolor"
    )
    console.print(f"[bold green]$[/] plainread explain shutoff-notice.jpg --today {today}")
    render(explanation, console)
    (OUT / "cli.svg").write_text(console.export_svg(title="plainread explain"), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default=dt.date.today().isoformat())
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.today)
    OUT.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    photo = letter_photo(today)
    cli_svg(today)
    base = start_server()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PLAINREAD_CHROMIUM") or None)

        # 1. Start page with a photographed letter added.
        page = browser.new_page(viewport={"width": 1180, "height": 980}, device_scale_factor=2)
        page.goto(f"{base}/?today={today}")
        page.wait_for_selector("#language option", state="attached")
        page.set_input_files("#file-input", str(photo))
        page.wait_for_selector("#page-list li")
        page.screenshot(path=str(OUT / "start.png"))

        # 2. Results for the photo (OCR path), top of the page.
        page.click("#explain")
        page.wait_for_selector("#results:not([hidden])", timeout=120_000)
        page.set_viewport_size({"width": 1180, "height": 1500})
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(OUT / "results.png"))

        # 3. "Show in letter" highlights the exact words.
        page.locator("section[aria-label='Important dates'] .linkbtn").first.click()
        page.wait_for_timeout(900)
        page.locator("#full-letter").scroll_into_view_if_needed()
        mark = page.locator("mark.flash")
        mark.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        box = page.locator("#full-letter").bounding_box()
        if box:
            page.screenshot(
                path=str(OUT / "show-in-letter.png"),
                clip={
                    "x": box["x"] - 24,
                    "y": box["y"] - 70,
                    "width": box["width"] + 48,
                    "height": min(box["height"] + 90, 760),
                },
            )
        page.close()

        # 4. Phone, in Spanish.
        phone = browser.new_context(**p.devices["iPhone 13"])
        mobile = phone.new_page()
        mobile.add_init_script("localStorage.setItem('plainread.lang', 'es')")
        mobile.goto(f"{base}/?today={today}")
        mobile.wait_for_selector("#sample-select option[value='court-summons']", state="attached")
        mobile.select_option("#sample-select", "court-summons")
        mobile.wait_for_timeout(400)
        mobile.click("#explain")
        mobile.wait_for_selector("#results:not([hidden])")
        mobile.wait_for_timeout(500)
        mobile.evaluate("document.activeElement.blur(); window.scrollTo(0, 0)")
        mobile.wait_for_timeout(300)
        mobile.screenshot(path=str(OUT / "mobile-es.png"))
        phone.close()

        # 5. Dark mode, results.
        dark = browser.new_context(
            color_scheme="dark", viewport={"width": 1180, "height": 1100}, device_scale_factor=2
        )
        dpage = dark.new_page()
        dpage.goto(f"{base}/?today={today}")
        dpage.wait_for_selector("#sample-select option[value='hospital-bill']", state="attached")
        dpage.select_option("#sample-select", "hospital-bill")
        dpage.wait_for_timeout(400)
        dpage.click("#explain")
        dpage.wait_for_selector("#results:not([hidden])")
        dpage.screenshot(path=str(OUT / "dark.png"))
        dark.close()
        browser.close()
    for path in sorted(OUT.iterdir()):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
