"""Drive the real web app in Chromium. Run with: pytest -m e2e"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    import uvicorn

    from plainread.api import create_app
    from plainread.config import Settings

    settings = Settings()
    settings.ai = "off"
    port = _free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser() -> Iterator[object]:
    with playwright_api.sync_playwright() as p:
        executable = os.environ.get("PLAINREAD_CHROMIUM") or None
        b = p.chromium.launch(executable_path=executable)
        yield b
        b.close()


def test_sample_letter_flow(server: str, browser) -> None:
    page = browser.new_context(bypass_csp=True).new_page()  # our CSP blocks eval()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{server}/?today=2026-03-02")
    page.wait_for_selector("#sample-select option[value='court-summons']", state="attached")
    page.select_option("#sample-select", "court-summons")
    page.wait_for_function("document.querySelector('#letter-text').value.length > 100")
    page.click("#explain")
    page.wait_for_selector("#results:not([hidden])")
    body = page.inner_text("#result-body")
    assert "Court letter" in body
    assert "Important dates" in body
    assert "SC-2026-004512" in body
    assert "[object" not in body
    # "Show in letter" opens the full letter and highlights the quote.
    page.locator(".linkbtn").first.click()
    assert page.locator("#full-letter").get_attribute("open") is not None
    assert page.locator("mark.flash").count() == 1
    # Switching language re-explains the letter.
    page.select_option("#language", "es")
    page.wait_for_function("document.documentElement.lang === 'es'")
    page.wait_for_function(
        "document.querySelector('#result-body').innerText.includes('Fechas importantes')"
    )
    assert errors == []


def test_empty_submit_shows_error(server: str, browser) -> None:
    page = browser.new_context(bypass_csp=True).new_page()  # our CSP blocks eval()
    page.goto(server)
    page.wait_for_selector("#language option", state="attached")
    page.click("#explain")
    assert page.locator("#start-error").is_visible()
