from __future__ import annotations

import asyncio
import json
import logging
import re
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
from .google import Google, save_report
from .jobs import preflight, workspace
from .model import Compatibility as C
from .model import warning
from .package import validate_upload_name
from .pipelines import describe, resolve

logger = logging.getLogger("workspace_toolkit")
STATIC = Path(__file__).parent / "static"


# Google's published conversion limits (support.google.com/drive/answer/37603),
# checked 2026-09-28 and not yet observed live. They are Google's, not ours:
# nothing is refused here, but a person should know before converting.
IMPORT_LIMITS = {
    "docx": ("Google Docs", 50_000_000),
    "pptx": ("Google Slides", 100_000_000),
    "xlsx": ("Google Sheets", 100_000_000),
}


# An IANA name such as Europe/London or America/Argentina/Buenos_Aires.
ZONE_NAME = re.compile(r"(?:[A-Za-z][A-Za-z0-9_+-]*/){0,2}[A-Za-z][A-Za-z0-9_+-]*")


def time_zone(header: str | None) -> str | None:
    """The browser's time zone, if it looks like one: a converted Sheet is
    given it so TODAY() and NOW() follow the person's own clock. Google is
    the final judge; sheets.convert falls back to London if it is refused."""
    value = (header or "").strip()
    return value if len(value) <= 64 and ZONE_NAME.fullmatch(value) else None


def import_limit_warning(key: str, size: int) -> list[dict]:
    if key not in IMPORT_LIMITS or size <= IMPORT_LIMITS[key][1]:
        return []
    product, limit = IMPORT_LIMITS[key]
    return [
        warning(
            "beyond_import_limit",
            f"The file sent to Google would be {size / 1_000_000:,.0f} MB. Google's published limit for "
            f"converting a file to {product} is {limit // 1_000_000} MB, so Google is "
            'likely to refuse it. If it holds photographs, converting with "Make '
            'pictures smaller" may bring it under.',
            classification=C.UNSUPPORTED,
            sizeBytes=size,
            limitBytes=limit,
            product=product,
        )
    ]


# How Google turning a file down shows here: its upload failing, or a call on
# the converted file failing. Too large for Google is the likely cause when the
# file was already over Google's published limit (#36).
REFUSED_BY_GOOGLE = {"upload_uncertain", "google_failed"}


def name_the_limit(report: dict, beyond: list[dict]) -> None:
    """Says plainly which limit a failed conversion ran into, where it was
    Google's size limit, so the person isn't left with a generic failure."""
    if not beyond or not str(report.get("status", "")).startswith("failed"):
        return
    if not any(w.get("code") in REFUSED_BY_GOOGLE for w in report.get("warnings", [])):
        return
    note = beyond[0]
    size, limit, product = note["sizeBytes"], note["limitBytes"], note["product"]
    report["stoppedBecause"] = (
        f"Google didn't convert it. The file is {size / 1_000_000:,.0f} MB, and Google's limit "
        f"for converting to {product} is {limit // 1_000_000} MB. If it holds photographs, try "
        'again with "Make pictures smaller".'
    )


def pictures_report(path: Path) -> tuple[dict, dict] | None:
    """What "Make pictures smaller" did: the details, and a note for a person."""
    if not path.exists():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    done = result.get("picturesCompressed") or []
    if result.get("failed"):
        note = warning(
            "pictures_not_compressed",
            "The pictures could not be made smaller, so they were converted at full size.",
            classification=C.IGNORED,
        )
    elif not done:
        note = warning(
            "pictures_already_small",
            "No pictures needed making smaller: none was larger than the size it is shown at.",
            classification=C.IGNORED,
        )
    else:
        before, after = result["bytesBefore"], result["bytesAfter"]
        note = warning(
            "pictures_compressed",
            f"{len(done)} picture{'s' if len(done) != 1 else ''} made smaller for Google, "
            f"reducing the file from {before / 1_000_000:,.1f} MB to {after / 1_000_000:,.1f} MB. "
            "Your original file is unchanged.",
            classification=C.SUBSTITUTED,
            count=len(done),
        )
    return result, note


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
        # Google Picker needs its own script and iframe origins, so the
        # default stays maximally strict and only loosens when the operator
        # has actually configured the feature (settings.picker_ready).
        # Verified live against a real GCP project (2026-09-28): gapi's own
        # picker widget sets inline style="..." attributes on elements it
        # creates in this page (not just inside its iframe), which needed
        # style-src 'unsafe-inline' -- there is no hash/nonce we can apply to
        # markup a third party generates. frame-src/script-src/connect-src
        # were confirmed sufficient as originally written.
        script_src = "'self'" + (" https://apis.google.com" if settings.picker_ready else "")
        # PrimaryTech brand.css @imports Source Sans 3 from Google Fonts
        # (see brand.css's own header) -- unconditional, unlike the Picker
        # additions below, since it isn't gated by any feature flag.
        style_src = "'self' https://fonts.googleapis.com" + (
            " 'unsafe-inline'" if settings.picker_ready else ""
        )
        frame_src = " frame-src https://docs.google.com;" if settings.picker_ready else ""
        connect_src = (
            " connect-src 'self' https://www.googleapis.com;" if settings.picker_ready else ""
        )
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src {script_src}; style-src {style_src}; "
            f"font-src 'self' https://fonts.gstatic.com; img-src 'self';"
            f"{frame_src}{connect_src} frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
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
                "formats": describe(settings),
                "pickerEnabled": settings.picker_ready,
                "pickerApiKey": settings.picker_api_key if settings.picker_ready else "",
                "pickerAppId": settings.picker_app_id if settings.picker_ready else "",
            }
        except ToolkitError:
            return {
                "signedIn": False,
                "configured": settings.oauth_ready,
                "maxUploadBytes": settings.max_upload_bytes,
                "formats": describe(settings),
                "pickerEnabled": settings.picker_ready,
                "pickerApiKey": "",
                "pickerAppId": "",
            }

    @app.get("/api/picker-token")
    async def picker_token(request: Request):
        # A read, not a state change, so no CSRF check -- same as
        # /api/session. Fetched fresh only when the picker is actually
        # opened, rather than embedded in the page on load, so it sits in
        # browser memory for as little time as possible.
        if not settings.picker_ready:
            raise ToolkitError(
                "picker_unavailable", "Adding a file from Drive is not available.", 503
            )
        data = auth.session(request)
        return {"accessToken": data["access_token"]}

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
            try:
                data = await auth.exchange(
                    request.query_params.get("code", ""),
                    request.query_params.get("state", ""),
                    request.cookies.get(STATE),
                    client,
                )
            except ToolkitError as error:
                if error.code != "account_not_allowed":
                    raise
                # Back to the page, which says why, not a bare JSON error.
                response = RedirectResponse("/?signin=not_allowed", status_code=302)
                response.delete_cookie(STATE)
                return response
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

    def over_limit(size: int) -> bool:
        return settings.max_upload_bytes is not None and size > settings.max_upload_bytes

    def require_time(session: dict, do_convert: bool, allowed: int) -> None:
        # Google's token lasts an hour, and a conversion is allowed `allowed`
        # seconds. Refuse up front rather than lose the token halfway through
        # the uploads and hand back a partial conversion.
        if do_convert and float(session["expires"]) - time.time() < allowed:
            raise ToolkitError(
                "session_expiring",
                "Your Google sign-in expires before a conversion could finish. "
                "Please sign out, sign in again, and convert.",
                401,
            )

    async def run(request: Request, do_convert: bool):
        session = auth.session(request, csrf=True)
        filename = unquote(request.headers.get("x-upload-filename", ""))
        pipeline = resolve(filename)
        validate_upload_name(filename, request.headers.get("content-type", ""), pipeline.fmt)
        if do_convert and not pipeline.convertible(settings):
            raise ToolkitError(
                "not_convertible",
                f"{pipeline.fmt.noun.capitalize()} files can be checked, but converting them "
                f"to {pipeline.destination} is not set up on this server.",
                501,
            )
        # A file picked from Drive (see the picker-token route and app.js)
        # arrives by id instead of a request body -- everything from here on
        # is shared between the two sources.
        drive_file_id = request.headers.get("x-drive-file-id") or None
        # Opt-in, and only for a conversion: checking a file never changes it.
        # Only a PowerPoint or Word file sent to Google can be made smaller:
        # Publisher pictures go to Slides one by one, by link.
        smaller = (
            do_convert
            and request.headers.get("x-compress-pictures") == "1"
            and pipeline.fmt.key in {"pptx", "docx"}
        )
        zone = time_zone(request.headers.get("x-time-zone"))
        if drive_file_id and not settings.picker_ready:
            raise ToolkitError(
                "picker_unavailable", "Adding a file from Drive is not available.", 503
            )
        declared = 0
        if drive_file_id is None:
            length = request.headers.get("content-length")
            if length:
                try:
                    declared = int(length)
                except ValueError as exc:
                    raise ToolkitError("invalid_size", "Invalid upload size.") from exc
                if declared < 0 or over_limit(declared):
                    raise ToolkitError(
                        "upload_too_large", "This file exceeds the upload size limit.", 413
                    )
        # A Drive file's size is unknown until it is fetched, so this is
        # checked again once it is on disk.
        require_time(session, do_convert, settings.job_timeout_for(declared))
        if gate.locked():
            raise ToolkitError("busy", "The converter is busy. Please try again shortly.", 503)
        async with gate:
            with workspace(settings) as (job_id, root):
                began = time.monotonic()
                progress: dict = {}
                try:
                    async with asyncio.timeout(settings.job_timeout_for(declared)) as deadline:
                        # Constructed unconditionally now rather than only at
                        # convert time: a Drive-sourced file needs it just to
                        # be fetched, even for an analyse-only request.
                        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                            google = Google(session["access_token"], client)

                            destination = root / pipeline.source_name

                            def allow_for(size: int) -> None:
                                allowed = settings.job_timeout_for(size)
                                require_time(session, do_convert, allowed)
                                deadline.reschedule(
                                    asyncio.get_running_loop().time()
                                    + allowed
                                    - (time.monotonic() - began)
                                )

                            if drive_file_id:
                                # Sized first, so the time allowed covers the
                                # download too: fetched unsized, a large file
                                # spent the base 240 s just arriving.
                                announced = await google.size(drive_file_id)
                                if announced:
                                    allow_for(announced)
                                size = await google.download(
                                    drive_file_id, destination, settings.max_upload_bytes
                                )
                                allow_for(size)
                            else:
                                size = 0
                                with destination.open("xb") as stream:
                                    async for chunk in request.stream():
                                        size += len(chunk)
                                        if over_limit(size):
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

                            manifest = await preflight(
                                root,
                                settings,
                                pipeline.fmt,
                                compress_pictures=smaller,
                                check_only=not do_convert,
                            )
                            # What Google receives: for a deck, without its video.
                            sent = root / "result" / ("converted" + pipeline.fmt.suffix)
                            beyond = import_limit_warning(
                                pipeline.fmt.key, sent.stat().st_size if sent.exists() else size
                            )
                            if not do_convert:
                                analysis = pipeline.analysis_report(manifest)
                                analysis.setdefault("warnings", []).extend(beyond)
                                return analysis
                            # Converting is one step (DECISIONS.md, 2026-09-29): a file
                            # need not be checked first. A client that did check it
                            # can still say which file it checked, and is held to it.
                            expected = request.headers.get("x-source-sha256")
                            if expected is not None and expected != manifest["source"]["sha256"]:
                                raise ToolkitError(
                                    "source_changed",
                                    "This file changed since it was checked. Please try again.",
                                    409,
                                )
                            report = await pipeline.convert(
                                root,
                                manifest,
                                google,
                                progress,
                                original_name=Path(filename).stem,
                                **({"settings": settings} if pipeline.needs_settings else {}),
                                **(
                                    {
                                        "time_zone": zone,
                                        "attach_macros": bool(session.get("scripts")),
                                    }
                                    if pipeline.needs_time_zone
                                    else {}
                                ),
                            )
                            # Added here rather than in each pipeline, so every
                            # format reports what happened in Drive the same way.
                            report.setdefault("warnings", []).extend(beyond + google.warnings)
                            name_the_limit(report, beyond)
                            outcome = pictures_report(root / "result" / "pictures.json")
                            if smaller and outcome:
                                report["pictures"], note = outcome
                                report["warnings"].append(note)
                            # Saved last, so the copy in Drive holds all of it.
                            await save_report(root, report, google)
                            return report
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
                                "fileType": pipeline.fmt.key,
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
