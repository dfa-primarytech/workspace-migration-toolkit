from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from .auth import SESSION, STATE, Auth
from .config import Settings
from .errors import ToolkitError
from .google import Google, convert
from .jobs import preflight, workspace
from .package import validate_upload_name
from .pptx import analysis_report

logger = logging.getLogger("workspace_toolkit")
STATIC = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    auth = Auth(settings)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.auth = auth
    app.state.settings = settings
    gate = asyncio.Semaphore(2)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.base_url).hostname or "localhost"]
    )

    @app.middleware("http")
    async def safe_errors(request: Request, call_next):
        try:
            response = await call_next(request)
        except ToolkitError as exc:
            response = JSONResponse(
                {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
            )
        except Exception:
            logger.error(json.dumps({"event": "request_failed", "code": "internal_error"}))
            response = JSONResponse(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "The operation could not be completed. Please try again.",
                    }
                },
                status_code=500,
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/session")
    async def session(request: Request):
        try:
            data = auth.session(request)
            return {
                "signedIn": True,
                "csrfToken": data["csrf"],
                "maxUploadBytes": settings.max_upload_bytes,
            }
        except ToolkitError:
            return {
                "signedIn": False,
                "configured": settings.oauth_ready,
                "maxUploadBytes": settings.max_upload_bytes,
            }

    @app.get("/auth/start")
    async def start():
        url, data = auth.start()
        response = RedirectResponse(url, status_code=302)
        auth.cookie(response, STATE, data, 600)
        return response

    @app.get("/auth/callback")
    async def callback(request: Request):
        if request.query_params.get("error"):
            response = RedirectResponse("/?signin=cancelled", status_code=302)
            response.delete_cookie(STATE)
            return response
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            data = await auth.exchange(
                request.query_params.get("code", ""),
                request.query_params.get("state", ""),
                request.cookies.get(STATE),
                client,
            )
        response = RedirectResponse("/", status_code=302)
        auth.cookie(response, SESSION, data, int(data["expires"] - time.time()))
        response.delete_cookie(STATE)
        return response

    @app.post("/auth/logout")
    async def logout(request: Request):
        auth.session(request, csrf=True)
        response = JSONResponse({"signedIn": False})
        response.delete_cookie(SESSION)
        return response

    async def run(request: Request, do_convert: bool):
        session = auth.session(request, csrf=True)
        filename = unquote(request.headers.get("x-upload-filename", ""))
        validate_upload_name(filename, request.headers.get("content-type", ""))
        length = request.headers.get("content-length")
        if length:
            try:
                declared = int(length)
            except ValueError as exc:
                raise ToolkitError("invalid_size", "Invalid upload size.") from exc
            if declared < 0 or declared > settings.max_upload_bytes:
                raise ToolkitError(
                    "upload_too_large", "This file exceeds the upload size limit.", 413
                )
        if gate.locked():
            raise ToolkitError("busy", "The converter is busy. Please try again shortly.", 503)
        async with gate:
            with workspace(settings) as (job_id, root):
                began = time.monotonic()
                progress: dict = {}
                try:
                    async with asyncio.timeout(settings.job_timeout):
                        size = 0
                        with (root / "source.pptx").open("xb") as stream:
                            async for chunk in request.stream():
                                size += len(chunk)
                                if size > settings.max_upload_bytes:
                                    raise ToolkitError(
                                        "upload_too_large",
                                        "This file exceeds the upload size limit.",
                                        413,
                                    )
                                stream.write(chunk)
                        if not size:
                            raise ToolkitError(
                                "empty_upload", "Please choose a file that is not empty."
                            )
                        manifest = await preflight(root, settings)
                        if not do_convert:
                            return analysis_report(manifest)
                        if request.headers.get("x-source-sha256") != manifest["source"]["sha256"]:
                            raise ToolkitError(
                                "source_changed",
                                "Please analyse this file before converting it.",
                                409,
                            )
                        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                            return await convert(
                                root,
                                manifest,
                                Google(session["access_token"], client),
                                progress,
                                output_name=Path(filename).stem + " – converted",
                            )
                except TimeoutError:
                    if progress.get("folderUrl"):
                        progress.update(
                            status="failed_with_partial_outputs", verification="incomplete"
                        )
                        progress.setdefault("warnings", []).append(
                            {
                                "code": "job_timeout",
                                "message": "Conversion timed out. Check the conversion folder before retrying.",
                            }
                        )
                        return progress
                    raise ToolkitError(
                        "job_timeout", "Processing took too long. Please try a smaller file.", 422
                    ) from None
                finally:
                    logger.info(
                        json.dumps(
                            {
                                "event": "job_finished",
                                "jobId": job_id,
                                "fileType": "pptx",
                                "durationMs": round((time.monotonic() - began) * 1000),
                            }
                        )
                    )

    @app.post("/api/analyse")
    async def analyse_route(request: Request):
        return await run(request, False)

    @app.post("/api/convert")
    async def convert_route(request: Request):
        return await run(request, True)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
