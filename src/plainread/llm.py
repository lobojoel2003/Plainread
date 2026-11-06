"""Optional local AI: plainer wording and full translation.

Plainread talks only to a model running on this device (Ollama, or any
OpenAI-compatible local server such as llama.cpp's ``llama-server``). Remote
endpoints are refused unless ``PLAINREAD_ALLOW_REMOTE_AI=1`` is set.

The AI never adds dates, amounts or numbers. It rewrites what the rules engine
found, and any new statement it makes must come with a quote that is found in
the letter, or it is thrown away.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from plainread import i18n
from plainread.config import Settings
from plainread.grounding import locate, make_quote
from plainread.models import Explanation, Point


class AIError(RuntimeError):
    """The local model could not be reached or gave an unusable answer."""


class RemoteAIRefusedError(AIError):
    """The configured AI endpoint is not on this device or local network."""


def is_local_url(url: str) -> bool:
    """True when ``url`` points at this machine or a private network address."""
    host = urlparse(url).hostname
    if not host:
        return False
    if host in ("localhost", "ip6-localhost"):
        return True
    try:
        addresses = {str(info[4][0]) for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return bool(addresses)


def _extract_json(content: str) -> dict[str, Any]:
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        raise AIError("The model did not return JSON")
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIError(f"The model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AIError("The model returned JSON that is not an object")
    return data


class LocalModel:
    """Base class for a local chat model that can return JSON."""

    backend = "base"

    def __init__(
        self, url: str, model: str, timeout: float = 300, allow_remote: bool = False
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        if not allow_remote and not is_local_url(self.url):
            raise RemoteAIRefusedError(
                f"{self.url} is not on this device. Plainread only uses local AI so your letters stay "
                "private. Set PLAINREAD_ALLOW_REMOTE_AI=1 to override."
            )

    @property
    def label(self) -> str:
        return self.model

    def available(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def chat_json(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class OllamaModel(LocalModel):
    backend = "ollama"

    def models(self) -> list[str]:
        try:
            response = httpx.get(f"{self.url}/api/tags", timeout=3)
            response.raise_for_status()
        except httpx.HTTPError:
            return []
        return [str(m.get("name", "")) for m in response.json().get("models", [])]

    def available(self) -> bool:
        names = self.models()
        wanted = self.model if ":" in self.model else self.model + ":latest"
        return any(n == self.model or n == wanted for n in names)

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = httpx.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIError(f"Ollama request failed: {exc}") from exc
        content = response.json().get("message", {}).get("content", "")
        return _extract_json(str(content))


class OpenAICompatibleModel(LocalModel):
    """llama.cpp ``llama-server``, LM Studio, vLLM and similar local servers."""

    backend = "openai"

    def available(self) -> bool:
        try:
            response = httpx.get(f"{self.url}/models", timeout=3)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object", "schema": schema},
            "messages": [
                {"role": "system", "content": system + "\nJSON schema:\n" + json.dumps(schema)},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = httpx.post(
                f"{self.url}/chat/completions", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIError(f"Local AI request failed: {exc}") from exc
        choices = response.json().get("choices") or [{}]
        content = choices[0].get("message", {}).get("content", "")
        return _extract_json(str(content))


def from_settings(settings: Settings) -> LocalModel | None:
    if settings.ai == "off":
        return None
    cls: type[LocalModel] = (
        OllamaModel if settings.ai_backend == "ollama" else OpenAICompatibleModel
    )
    return cls(settings.ai_url, settings.model, settings.ai_timeout, settings.allow_remote_ai)


_POINT = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "quote": {"type": "string"}},
    "required": ["text", "quote"],
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "array", "items": _POINT, "maxItems": 4},
        "rewrites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        },
        "missing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["action", "consequence", "right"]},
                    "text": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["category", "text", "quote"],
            },
        },
    },
    "required": ["summary", "rewrites", "missing"],
}

SYSTEM_PROMPT = """You help people who find official letters hard to read.
Write in very plain {language} at a 5th-grade reading level: short sentences, everyday words, and speak to the reader as "you".
Rules:
1. Only use facts that are written in the letter. Never guess, and never add advice that is not in the letter.
2. Keep every date, time, amount of money, phone number and ID number exactly as the letter gives it.
3. A "quote" must be copied word for word from the letter, in the letter's own language. Keep quotes to one sentence or less.
4. Write every "text" in {language}.
5. Answer with JSON only."""

USER_PROMPT = """LETTER:
<<<
{letter}
>>>

A checker already found the items below in the letter. Each has an id.
{items}

Do three things:
1. "summary": 2 to 4 short sentences in {language} that say what this letter is about and what matters most. Give each one a supporting "quote" from the letter.
2. "rewrites": for EVERY id above, write that item again in plain {language} ("id" and "text"). For dates (ids starting with "d"), say what the reader must do or what happens on that date.
3. "missing": anything the reader must do (category "action"), what happens if they do nothing ("consequence"), or their rights and free help ("right") that the list above does not cover. Give each a "quote". Use an empty list if nothing is missing."""


def _items(e: Explanation) -> tuple[str, dict[str, Any]]:
    lines: list[str] = []
    targets: dict[str, Any] = {}

    def add(prefix: str, title: str, entries: list[Any], show: Any) -> None:
        if not entries:
            return
        lines.append(f"{title}:")
        for i, entry in enumerate(entries, 1):
            key = f"{prefix}{i}"
            targets[key] = entry
            lines.append(f"  [{key}] {show(entry)}")

    add("k", "Main points", e.key_points, lambda p: p.quote.text.replace("\n", " "))
    add(
        "d",
        "Dates",
        e.dates,
        lambda x: f"{x.date.isoformat()} ({x.kind}): {x.quote.text.replace(chr(10), ' ')}",
    )
    add("a", "Things to do", e.actions, lambda p: p.quote.text.replace("\n", " "))
    add("c", "If you do nothing", e.consequences, lambda p: p.quote.text.replace("\n", " "))
    add("r", "Rights and help", e.rights, lambda p: p.quote.text.replace("\n", " "))
    add("w", "Hard words (explain the meaning)", e.glossary, lambda g: f"{g.term}: {g.meaning}")
    return "\n".join(lines) or "(none)", targets


def enhance(e: Explanation, model: LocalModel) -> Explanation:
    """Rewrite and translate an explanation with a local model, keeping it grounded."""
    language = i18n.language_name(e.language)
    items, targets = _items(e)
    system = SYSTEM_PROMPT.format(language=language)
    user = USER_PROMPT.format(letter=e.source_text[:16000], items=items, language=language)
    data = model.chat_json(system, user, SCHEMA)
    text = e.source_text
    dropped = 0

    def clean(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:500]

    for rewrite in data.get("rewrites") or []:
        if not isinstance(rewrite, dict):
            continue
        target = targets.get(clean(rewrite.get("id")))
        new_text = clean(rewrite.get("text"))
        if target is None or not new_text:
            continue
        if isinstance(target, Point):
            target.text = new_text
            target.source = "ai"
        elif hasattr(target, "description"):
            target.description = new_text
            target.source = "ai"
        elif hasattr(target, "meaning"):
            target.meaning = new_text

    summary: list[Point] = []
    for item in data.get("summary") or []:
        if not isinstance(item, dict):
            continue
        span = locate(text, clean(item.get("quote")))
        if not span or not clean(item.get("text")):
            dropped += 1
            continue
        summary.append(Point(text=clean(item["text"]), quote=make_quote(text, *span), source="ai"))
    if summary:
        e.key_points = summary

    buckets = {"action": e.actions, "consequence": e.consequences, "right": e.rights}
    for item in data.get("missing") or []:
        if not isinstance(item, dict):
            continue
        bucket = buckets.get(clean(item.get("category")))
        span = locate(text, clean(item.get("quote")))
        if bucket is None or not span or not clean(item.get("text")):
            dropped += 1
            continue
        if any(p.quote.start < span[1] and span[0] < p.quote.end for p in bucket):
            continue  # already covered by the rules engine
        bucket.append(Point(text=clean(item["text"]), quote=make_quote(text, *span), source="ai"))

    if dropped:
        e.warnings.append(i18n.tn(e.language, "warnings.ai_dropped", dropped))
    e.engine = f"rules+ai:{model.backend}:{model.label}"
    return e
