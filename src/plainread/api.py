"""The local web app and JSON API (FastAPI).

Run it with ``plainread serve``. It listens on 127.0.0.1 by default, so only
this computer can reach it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from importlib import resources
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from plainread import i18n, llm, ocr, samples
from plainread.config import Settings
from plainread.ics import build_calendar
from plainread.models import Explanation, ImportantDate
from plainread.pipeline import Upload, explain_text, explain_uploads
from plainread.version import build_info

log = logging.getLogger(__name__)

CSP = (
    "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    language: str = "en"
    use_ai: bool = False
    today: dt.date | None = None


class CalendarRequest(BaseModel):
    dates: list[ImportantDate]
    sender: str | None = None


def _web_dir() -> str:
    return str(resources.files("plainread") / "web")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Plainread",
        version=build_info()["version"],
        description="Explain hard letters in plain language, privately, on your own device.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(SecurityHeaders)
    app.state.settings = settings

    def model() -> llm.LocalModel | None:
        try:
            return llm.from_settings(settings)
        except llm.RemoteAIRefusedError as exc:
            log.error("%s", exc)
            return None

    def ai_for(request_ai: bool) -> llm.LocalModel | None:
        if not request_ai:
            return None
        m = model()
        if m is None or not m.available():
            return None
        return m

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        m = model()
        ai_ready = bool(m and m.available())
        return {
            "status": "ok",
            **build_info(),
            "ocr": {"available": ocr.ocr_available(), "version": ocr.tesseract_version()},
            "ai": {
                "enabled": settings.ai != "off",
                "available": ai_ready,
                "backend": settings.ai_backend,
                "model": settings.model,
            },
            "max_upload_mb": settings.max_upload_mb,
        }

    @app.get("/api/languages")
    def languages() -> list[dict[str, str]]:
        return i18n.languages()

    @app.get("/api/i18n/{code}")
    def locale(code: str) -> JSONResponse:
        resolved = i18n.resolve(code)
        return JSONResponse(i18n.load(resolved))

    @app.get("/api/samples")
    def sample_list() -> list[dict[str, str]]:
        return samples.list_samples()

    @app.get("/api/samples/{sample_id}")
    def sample(sample_id: str, today: dt.date | None = None) -> dict[str, str]:
        try:
            return samples.get_sample(sample_id, today)
        except KeyError as exc:
            raise HTTPException(404, "Sample not found") from exc

    @app.post("/api/explain/text")
    def explain_text_endpoint(body: TextRequest) -> Explanation:
        return explain_text(
            body.text,
            language=body.language,
            today=body.today,
            date_order=settings.date_order,
            ai=ai_for(body.use_ai),
        )

    @app.post("/api/explain")
    async def explain_endpoint(
        files: Annotated[list[UploadFile] | None, File()] = None,
        text: Annotated[str | None, Form()] = None,
        language: Annotated[str, Form()] = "en",
        use_ai: Annotated[bool, Form()] = False,
        today: Annotated[dt.date | None, Form()] = None,
    ) -> Explanation:
        lang = i18n.resolve(language)
        uploads: list[Upload] = []
        limit = settings.max_upload_mb * 1024 * 1024
        for f in (files or [])[: settings.max_files]:
            data = await f.read(limit + 1)
            if len(data) > limit:
                raise HTTPException(413, i18n.t(lang, "ui.error_too_big"))
            if data:
                uploads.append(Upload(data, f.filename or "", f.content_type))
        kwargs: dict[str, Any] = {
            "language": lang,
            "today": today,
            "date_order": settings.date_order,
            "ai": ai_for(use_ai),
        }
        if uploads:
            try:
                return explain_uploads(uploads, ocr_lang=settings.ocr_lang, **kwargs)
            except ocr.UnsupportedFileError as exc:
                raise HTTPException(415, i18n.t(lang, "ui.error_type")) from exc
            except ocr.OcrUnavailableError as exc:
                raise HTTPException(503, i18n.t(lang, "warnings.ocr_unavailable")) from exc
        if text and text.strip():
            return explain_text(text, **kwargs)
        raise HTTPException(400, i18n.t(lang, "ui.error_empty"))

    @app.post("/api/calendar")
    def calendar(body: CalendarRequest) -> Response:
        content = build_calendar(body.dates, body.sender)
        return Response(
            content,
            media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="plainread-dates.ics"'},
        )

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(f"{_web_dir()}/index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> Response:
        content = (resources.files("plainread") / "web" / "manifest.webmanifest").read_text("utf-8")
        return Response(json.dumps(json.loads(content)), media_type="application/manifest+json")

    app.mount("/static", StaticFiles(directory=_web_dir()), name="static")
    return app
