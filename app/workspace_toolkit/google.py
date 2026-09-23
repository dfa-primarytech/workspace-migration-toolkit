from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning
from .package import PPTX_MIME
from .pptx import analysis_report

SLIDES_MIME = "application/vnd.google-apps.presentation"
DOCS_MIME = "application/vnd.google-apps.document"
DRIVE = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
# One home for every conversion, with a dated subfolder per job inside it.
LIBRARY = "Workspace conversions"

# Drive throttles a burst of uploads per user. These are the replies worth
# waiting out; anything else is a real refusal and retrying only hides it.
TRANSIENT = frozenset({408, 429, 500, 502, 503, 504})
UPLOAD_ATTEMPTS = 4


def http_status(exc: BaseException) -> int | None:
    """The status Google replied with, when the failure came back as a reply."""
    return getattr(getattr(exc, "response", None), "status_code", None)


def failure_detail(exc: BaseException) -> str:
    """A short, safe hint about a failure: the status, or the transport fault."""
    status = http_status(exc)
    return f"http_{status}" if status is not None else type(exc).__name__


def is_transient(exc: BaseException) -> bool:
    """Whether waiting and asking again could plausibly succeed."""
    status = http_status(exc)
    if status is not None:
        return status in TRANSIENT
    return isinstance(exc, httpx.TransportError)


class Google:
    def __init__(self, token: str, client: httpx.AsyncClient):
        self.client = client
        self.headers = {"Authorization": "Bearer " + token}

    async def request(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = await self.client.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            result = response.json() if response.content else {}
            if not isinstance(result, dict):
                raise ValueError("Unexpected Google response")
            return result
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolkitError(
                "google_failed",
                "Google could not complete this operation. Check the report before retrying.",
                502,
                detail=failure_detail(exc),
            ) from exc

    async def make_folder(self, name: str, parent: str | None = None) -> str:
        metadata: dict = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            metadata["parents"] = [parent]
        result = await self.request(
            "POST", DRIVE + "/files", json=metadata, params={"fields": "id"}
        )
        folder_id = result.get("id")
        if not isinstance(folder_id, str) or not folder_id:
            raise ToolkitError(
                "google_failed", "Google could not create the conversion folder.", 502
            )
        return folder_id

    async def library(self) -> str:
        """The one top-level folder that holds every conversion, made once.

        Under the `drive.file` scope a search only ever returns files this app
        created, so this can never adopt a folder of the person's own that
        happens to share the name.
        """
        found = await self.request(
            "GET",
            DRIVE + "/files",
            params={
                "q": f"mimeType='{FOLDER_MIME}' and name='{LIBRARY}' and trashed=false",
                "fields": "files(id)",
                "orderBy": "createdTime",
                "pageSize": 1,
                "spaces": "drive",
            },
        )
        existing = found.get("files") or []
        if existing and isinstance(existing[0].get("id"), str):
            return existing[0]["id"]
        return await self.make_folder(LIBRARY)

    async def folder(self, job_name: str = "Conversion") -> str:
        """A fresh subfolder for this job, inside the shared library folder."""
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H%M%S")
        return await self.make_folder(f"{job_name} ({stamp} UTC)", await self.library())

    async def upload(
        self,
        path: Path,
        name: str,
        mime: str,
        parent: str,
        convert: bool = False,
        target: str = SLIDES_MIME,
        retry: bool = False,
    ) -> dict:
        """Uploads one file. `retry` is for copies a duplicate would not spoil.

        The document itself is uploaded without retrying: a lost reply can still
        mean success, and asking twice would leave the person with two of them.
        A private asset copy has no such hazard, so a throttled one is worth
        waiting out rather than abandoning.
        """
        attempts = UPLOAD_ATTEMPTS if retry else 1
        delay = 1.0
        for attempt in range(1, attempts + 1):
            try:
                return await self._upload_once(path, name, mime, parent, convert, target)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                if attempt == attempts or not is_transient(exc):
                    # Never retry creation blindly: a lost response can still mean success.
                    raise ToolkitError(
                        "upload_uncertain",
                        "A Google upload failed or its result is uncertain. "
                        "Check the conversion folder before retrying.",
                        502,
                        detail=failure_detail(exc),
                    ) from exc
                await asyncio.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")

    async def _upload_once(
        self,
        path: Path,
        name: str,
        mime: str,
        parent: str,
        convert: bool,
        target: str,
    ) -> dict:
        metadata = {"name": name, "mimeType": target if convert else mime, "parents": [parent]}
        response = await self.client.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "resumable", "fields": "id,webViewLink,mimeType"},
            headers={
                **self.headers,
                "X-Upload-Content-Type": mime,
                "X-Upload-Content-Length": str(path.stat().st_size),
            },
            json=metadata,
        )
        response.raise_for_status()
        location = response.headers["Location"]
        parsed = urlsplit(location)
        if parsed.scheme != "https" or parsed.hostname not in {
            "www.googleapis.com",
            "content.googleapis.com",
        }:
            raise ValueError("Invalid upload destination")

        async def chunks():
            with path.open("rb") as stream:
                while block := stream.read(256 * 1024):
                    yield block

        uploaded = await self.client.put(
            location,
            headers={
                **self.headers,
                "Content-Type": mime,
                "Content-Length": str(path.stat().st_size),
            },
            content=chunks(),
        )
        uploaded.raise_for_status()
        result = uploaded.json()
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            raise ValueError("Unexpected upload response")
        return result

    async def export_text(self, file_id: str) -> str:
        """Reads a converted file back as plain text.

        Uses Drive export rather than the Docs API so no extra OAuth scope is
        needed: drive.file already covers files this application created.
        """
        try:
            response = await self.client.get(
                DRIVE + f"/files/{file_id}/export",
                headers=self.headers,
                params={"mimeType": "text/plain"},
            )
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            raise ToolkitError(
                "verification_unavailable",
                "The converted file could not be read back for checking.",
                502,
            ) from exc

    async def inspect(self, presentation_id: str) -> dict:
        return await self.request(
            "GET", f"https://slides.googleapis.com/v1/presentations/{presentation_id}"
        )


def google_text(element: dict) -> str:
    fragments = []
    for item in element.get("shape", {}).get("text", {}).get("textElements", []):
        fragments.append(item.get("textRun", {}).get("content", ""))
    for row in element.get("table", {}).get("tableRows", []):
        for cell in row.get("tableCells", []):
            fragments.append(
                "".join(
                    e.get("textRun", {}).get("content", "")
                    for e in cell.get("text", {}).get("textElements", [])
                )
            )
    for child in element.get("elementGroup", {}).get("children", []):
        fragments.append(google_text(child))
    return " ".join(fragment for fragment in fragments if fragment)


def google_object_counts(elements: list[dict]) -> Counter:
    counts: Counter = Counter()
    for element in elements:
        if "image" in element:
            counts["image"] += 1
        if "table" in element:
            counts["table"] += 1
        if "sheetsChart" in element:
            counts["chart"] += 1
        children = element.get("elementGroup", {}).get("children", [])
        if children:
            counts.update(google_object_counts(children))
    return counts


def verify(manifest: dict, presentation: dict) -> list[dict]:
    findings = []
    slides = presentation.get("slides", [])
    if len(slides) != len(manifest["pages"]):
        findings.append(
            warning(
                "page_count_changed",
                "The number of slides changed during import.",
                classification=C.UNSUPPORTED,
            )
        )
    page_size = presentation.get("pageSize", {})
    for axis in ("width", "height"):
        dimension = page_size.get(axis, {})
        magnitude = dimension.get("magnitude", 0)
        actual = (
            magnitude / 12700
            if dimension.get("unit") == "EMU"
            else magnitude
            if dimension.get("unit") == "PT"
            else None
        )
        if actual is None or abs(actual - manifest["document"][axis + "Pt"]) > 0.1:
            findings.append(
                warning(
                    "page_size_changed",
                    "Slide dimensions could not be verified against the original.",
                    classification=C.UNSUPPORTED,
                )
            )
            break
    for source, target in zip(manifest["pages"], slides, strict=False):
        original = " ".join(
            "".join(run["text"] for run in paragraph["runs"])
            for element in source["elements"]
            for paragraph in element["paragraphs"]
        )
        converted = " ".join(google_text(e) for e in target.get("pageElements", []))
        # Whitespace-normalised token multiset catches missing/repeated text without
        # publishing it in the conversion report. This does not prove layout fidelity.
        missing = Counter(original.split()) - Counter(converted.split())
        if missing:
            findings.append(
                warning(
                    "text_mismatch",
                    "Some source text could not be verified after import.",
                    slideIndex=source["index"],
                    missingTokenCount=sum(missing.values()),
                    classification=C.UNSUPPORTED,
                )
            )
        source_counts = Counter(
            element["type"]
            for element in source["elements"]
            if element["type"] in {"image", "table", "chart"}
        )
        converted_counts = google_object_counts(target.get("pageElements", []))
        for kind in ("image", "table", "chart"):
            if converted_counts[kind] < source_counts[kind]:
                findings.append(
                    warning(
                        "object_count_changed",
                        f"Some source {kind} objects could not be verified after import.",
                        slideIndex=source["index"],
                        objectType=kind,
                        sourceCount=source_counts[kind],
                        convertedCount=converted_counts[kind],
                        classification=C.UNSUPPORTED,
                    )
                )
    findings.append(
        warning(
            "visual_review_required",
            "Review images, layout, tables, fonts and media playback in the converted presentation. These have not been verified automatically.",
            classification=C.UNSUPPORTED,
        )
    )
    return findings


# A saved asset called "9f3c1a2b…" with no extension tells you nothing. To put a
# picture back into a deck by hand you need to know which slide wanted it, so
# that is what these names carry: the deck, the slide, and a suffix the
# computer recognises.
SEPARATOR = " – "  # en dash, matching the converted file's own name
NAME_LIMIT = 80  # characters of the source's name kept in every asset name
SLIDES_LISTED = 3  # beyond this, an asset is a logo or a background, not content

# Drive itself accepts almost anything, but these names are meant to survive
# being downloaded onto a desktop, where they are not.
UNSAFE = re.compile(r"[\\/:*?\"<>|]")

# Every type we extract, named here rather than guessed: see extension().
EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-emf": ".emf",
    "image/x-wmf": ".wmf",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


def clean_name(name: str) -> str:
    """A source file's own name, made safe to put inside a Drive filename."""
    stripped = "".join(character for character in name if ord(character) >= 32)
    return " ".join(UNSAFE.sub(" ", stripped).split())[:NAME_LIMIT].strip()


def extension(mime: str) -> str:
    """The suffix to give a saved asset, or nothing if the type is unlisted.

    Deliberately not `mimetypes.guess_extension`: its answers come from the
    host's registry or /etc/mime.types, so the same file would be named one
    thing on a laptop and another in the container. A name that changes with
    the machine is worse than a name with no suffix at all.
    """
    return EXTENSIONS.get(mime.split(";", 1)[0].strip().lower(), "")


def _slide_phrase(numbers: list[int], width: int) -> str:
    """Which slides used an asset, in words. Empty when nothing placed it."""
    if not numbers:
        return ""
    shown = [f"{number:0{width}d}" for number in numbers[:SLIDES_LISTED]]
    if len(numbers) == 1:
        return f"slide {shown[0]}"
    if len(numbers) <= SLIDES_LISTED:
        return "slides " + ", ".join(shown)
    return f"slides {shown[0]} and {len(numbers) - 1} more"


def _placements(manifest: dict) -> dict[str, list[int]]:
    """The slide numbers each asset appears on, in slide order.

    Only a presentation records this: a document's elements never name the
    assets they draw, and its "pages" are section breaks rather than the pages
    a reader would count, so numbering them would say something untrue.
    """
    if manifest.get("source", {}).get("type") != "pptx":
        return {}
    placed: dict[str, list[int]] = {}
    for page in manifest.get("pages") or []:
        index = page.get("index")
        if not isinstance(index, int):
            continue
        number = index + 1  # the manifest counts slides from zero; people do not
        for element in page.get("elements") or []:
            for asset_id in element.get("assetIds") or []:
                slides = placed.setdefault(asset_id, [])
                if number not in slides:
                    slides.append(number)
    return placed


def asset_names(manifest: dict, original_name: str = "") -> dict[str, str]:
    """A name for every asset that says where it came from, keyed by asset id.

    Assets are numbered in the order they first appear, so the numbering
    follows the deck rather than the order the archive happened to store them
    in. An asset nothing placed -- one used only by a layout or a master --
    keeps a name without a slide rather than being given a misleading one.
    """
    placed = _placements(manifest)
    width = len(str(max((slides[-1] for slides in placed.values()), default=0)))
    deck = clean_name(original_name)
    assets = list(manifest.get("assets", {}).values())
    # Unplaced assets sort last, and ties keep the manifest's own order.
    ranked = sorted(
        enumerate(assets),
        key=lambda pair: (placed.get(pair[1]["id"], [10**9])[0], pair[0]),
    )
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for _, asset in ranked:
        kind = asset.get("kind") or "file"
        counts[kind] += 1
        parts = [
            part
            for part in (
                deck,
                _slide_phrase(placed.get(asset["id"], []), width),
                f"{kind} {counts[kind]}",
            )
            if part
        ]
        names[asset["id"]] = SEPARATOR.join(parts) + extension(asset.get("mimeType", ""))
    return names


# Google's importer brings ordinary pictures into the document itself, so
# copying them out beside it preserves nothing: a worksheet's 65 photographs
# became 65 uploads, 65 files to scroll past, and 65 chances to be throttled,
# all for pictures that had already arrived safely. What the importer really
# does drop is embedded audio, video and OLE objects -- the sound on a slide,
# the spreadsheet inside a report -- and picture formats no browser draws.
# Those are the copies worth making.
DRAWN_BY_BROWSERS = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp", "image/svg+xml"}
)


def at_risk(asset: dict) -> bool:
    """Whether the importer is likely to drop this, making a copy worth keeping."""
    if asset.get("kind") != "image":
        return True  # audio, video and embedded objects do not survive the import
    return asset.get("mimeType", "").split(";", 1)[0].strip().lower() not in DRAWN_BY_BROWSERS


async def save_assets(
    result: Path,
    manifest: dict,
    google: Google,
    folder: str,
    report: dict,
    original_name: str = "",
) -> None:
    """Copies every extracted asset beside the converted file.

    These copies are a safety net, not the deliverable: they exist so anything the
    importer drops is still recoverable by hand. So one refused copy must not
    abandon the rest, and must never stop the document itself being verified.

    Recovering by hand means finding the right picture and putting it back where
    it belongs, so each copy is named after the deck and the slide it came from.
    The report keeps the asset id beside that name, so a file in Drive can still
    be matched to the manifest.

    Only what the importer is likely to drop is copied. Everything the document
    kept is already in the document, and a folder holding a second copy of it is
    not a safety net, only clutter to search through.
    """
    names = asset_names(manifest, original_name)
    at_hazard = [asset for asset in manifest["assets"].values() if at_risk(asset)]
    report["assetsNotCopied"] = len(manifest["assets"]) - len(at_hazard)
    failures: list[str] = []
    for asset in at_hazard:
        try:
            saved = await google.upload(
                result / asset["path"],
                names[asset["id"]],
                asset["mimeType"],
                folder,
                retry=True,
            )
        except ToolkitError as exc:
            failures.append(exc.detail or "unknown")
            continue
        report["assetOutputs"].append(
            {
                "assetId": asset["id"],
                "name": names[asset["id"]],
                "kind": asset["kind"],
                "driveFileId": saved["id"],
                "url": "https://drive.google.com/file/d/" + saved["id"] + "/view",
            }
        )
    if failures:
        report["warnings"].append(
            warning(
                "asset_copies_incomplete",
                f"{len(failures)} of {len(at_hazard)} private asset copies "
                "could not be saved to Drive. The converted file itself is unaffected; "
                "these copies are only a fallback for recovering anything the importer drops.",
                classification=C.IGNORED,
                attempted=len(at_hazard),
                saved=len(at_hazard) - len(failures),
                reasons=sorted(set(failures)),
            )
        )


async def convert(
    root: Path,
    manifest: dict,
    google: Google,
    progress: dict | None = None,
    original_name: str = "",
) -> dict:
    report = progress if progress is not None else {}
    deck = clean_name(original_name)
    output_name = f"{deck}{SEPARATOR}converted" if deck else "Converted presentation"
    report.update(analysis_report(manifest))
    report.update(status="converting", outputs=[], assetOutputs=[])
    try:
        formats = await google.request("GET", DRIVE + "/about", params={"fields": "importFormats"})
        if SLIDES_MIME not in formats.get("importFormats", {}).get(PPTX_MIME, []):
            raise ToolkitError(
                "conversion_unavailable",
                "Google does not currently offer PowerPoint conversion for this account.",
                422,
            )
        folder = await google.folder(output_name)
        report["folderUrl"] = "https://drive.google.com/drive/folders/" + folder
        rendered = root / "result" / "converted.pptx"
        result = await google.upload(
            rendered if rendered.exists() else root / "source.pptx",
            output_name,
            PPTX_MIME,
            folder,
            convert=True,
        )
        report["outputs"].append({"kind": "presentation", "id": result["id"]})
        report["presentationId"] = result["id"]
        report["url"] = "https://docs.google.com/presentation/d/" + result["id"] + "/edit"
        # Preserve every extracted asset privately, including audio/video that the
        # native importer might omit. No public permissions or automatic execution.
        await save_assets(root / "result", manifest, google, folder, report, original_name)
        presentation = await google.inspect(result["id"])
        report["warnings"].extend(verify(manifest, presentation))
        render_report = root / "result" / "render.json"
        if render_report.exists():
            rendered_details = json.loads(render_report.read_text(encoding="utf-8"))
            report["conversion"] = {
                "fontSubstitutions": rendered_details.get("fontSubstitutions", [])
            }
        report["verification"] = "page_size_count_and_text_checked"
        report["status"] = "completed_with_warnings"
    except ToolkitError as exc:
        report["status"] = "failed_with_partial_outputs" if report.get("folderUrl") else "failed"
        report["warnings"].append(
            warning(exc.code, exc.message, classification=C.UNSUPPORTED, detail=exc.detail)
            if exc.detail
            else warning(exc.code, exc.message, classification=C.UNSUPPORTED)
        )
        report["verification"] = "incomplete"
    if report.get("folderUrl"):
        report_path = root / "conversion-report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        try:
            saved = await google.upload(
                report_path,
                "Conversion report.json",
                "application/json",
                report["folderUrl"].rsplit("/", 1)[-1],
            )
            report["reportUrl"] = "https://drive.google.com/file/d/" + saved["id"] + "/view"
        except ToolkitError:
            report["warnings"].append(
                warning(
                    "report_upload_failed",
                    "The report could not be saved to Drive. Download it from this page.",
                )
            )
    return report
