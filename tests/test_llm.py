from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from plainread import llm
from plainread.pipeline import explain_text

from .conftest import COURT_LETTER, TODAY


class FakeModel(llm.LocalModel):
    """A stand-in for a local model that returns a fixed answer."""

    backend = "fake"

    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        super().__init__("http://127.0.0.1:1", "fake-model")
        self.answer = answer
        self.prompts: list[str] = []

    def available(self) -> bool:
        return True

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.prompts.append(system + "\n" + user)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_is_local_url():
    assert llm.is_local_url("http://127.0.0.1:11434")
    assert llm.is_local_url("http://localhost:11434")
    assert llm.is_local_url("http://[::1]:8080/v1")
    assert llm.is_local_url("http://192.168.1.20:11434")
    assert not llm.is_local_url("https://8.8.8.8/v1")
    assert not llm.is_local_url("not a url")


def test_remote_endpoints_are_refused():
    with pytest.raises(llm.RemoteAIRefusedError):
        llm.OllamaModel("https://8.8.8.8", "gemma3:4b")
    # ...unless explicitly allowed.
    assert (
        llm.OllamaModel("https://8.8.8.8", "gemma3:4b", allow_remote=True).url == "https://8.8.8.8"
    )


def test_extract_json_handles_thinking_and_fences():
    raw = '<think>hmm</think>\n```json\n{"summary": [], "rewrites": [], "missing": []}\n```'
    assert llm._extract_json(raw) == {"summary": [], "rewrites": [], "missing": []}
    with pytest.raises(llm.AIError):
        llm._extract_json("sorry, I cannot help")


def test_enhance_rewrites_and_drops_ungrounded_statements():
    answer = {
        "summary": [
            {
                "text": "Te demandan por $1,250.",
                "quote": "You are being sued by Pinecrest Property Management",
            },
            {
                "text": "Debe pagar $9,999 hoy.",
                "quote": "You must pay $9,999 today.",
            },  # not in letter
        ],
        "rewrites": [
            {"id": "a1", "text": "Vaya a la corte el 20 de marzo a las 9:00 AM."},
            {"id": "d1", "text": "Fecha límite para su respuesta escrita."},
            {"id": "zz", "text": "ignored"},
        ],
        "missing": [
            {"category": "action", "text": "Lleve su identificación.", "quote": "Photo ID"},
            {"category": "right", "text": "Inventado", "quote": "You may skip court."},
        ],
    }
    model = FakeModel(answer)
    e = explain_text(COURT_LETTER, today=TODAY, language="es", ai=model)
    assert e.engine == "rules+ai:fake:fake-model"
    assert [p.text for p in e.key_points] == ["Te demandan por $1,250."]
    assert e.key_points[0].source == "ai"
    assert e.actions[0].text == "Vaya a la corte el 20 de marzo a las 9:00 AM."
    assert e.dates[0].description == "Fecha límite para su respuesta escrita."
    # Dates themselves never come from the AI.
    assert [d.date.isoformat() for d in e.dates] == ["2026-03-16", "2026-03-20"]
    assert any("2" in w and "IA" in w for w in e.warnings)  # two statements were dropped
    for quote in e.all_quotes():
        assert e.source_text[quote.start : quote.end] == quote.text
    assert "Spanish" in model.prompts[0]


def test_enhance_failure_falls_back_to_rules():
    e = explain_text(COURT_LETTER, today=TODAY, ai=FakeModel(llm.AIError("boom")))
    assert e.engine == "rules"
    assert any("did not answer" in w for w in e.warnings)


def test_ollama_backend(monkeypatch):
    calls: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        calls["url"] = url
        calls["payload"] = json
        content = '{"summary": [], "rewrites": [], "missing": []}'
        return httpx.Response(
            200, json={"message": {"content": content}}, request=httpx.Request("POST", url)
        )

    def fake_get(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(
            200, json={"models": [{"name": "gemma3:4b"}]}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm.httpx, "get", fake_get)
    model = llm.OllamaModel("http://127.0.0.1:11434", "gemma3:4b")
    assert model.available()
    assert model.chat_json("sys", "user", llm.SCHEMA) == {
        "summary": [],
        "rewrites": [],
        "missing": [],
    }
    assert calls["url"].endswith("/api/chat")
    assert calls["payload"]["format"] == llm.SCHEMA
    assert calls["payload"]["options"]["temperature"] == 0


def test_openai_compatible_backend(monkeypatch):
    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        body = {
            "choices": [{"message": {"content": '{"summary": [], "rewrites": [], "missing": []}'}}]
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    model = llm.OpenAICompatibleModel("http://127.0.0.1:8080/v1", "local")
    assert model.chat_json("sys", "user", llm.SCHEMA)["missing"] == []


def test_ollama_errors_become_ai_errors(monkeypatch):
    def broken(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm.httpx, "post", broken)
    monkeypatch.setattr(llm.httpx, "get", broken)
    model = llm.OllamaModel("http://127.0.0.1:11434", "gemma3:4b")
    assert model.available() is False
    with pytest.raises(llm.AIError):
        model.chat_json("s", "u", llm.SCHEMA)


def test_schema_is_valid_json():
    json.dumps(llm.SCHEMA)
