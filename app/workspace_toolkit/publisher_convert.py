"""Sends a planned Publisher conversion to Google Slides (Publisher step 3).

The worker has already parsed the file, drawn its pictures and written
`plan.json` (publisher.render_path). This builds the presentation from it:

1. create the presentation at the publication's page size, in the job's
   folder, and read back the size Google actually gave it;
2. make one blank slide per page and remove the one Google starts with;
3. for each page: store its pictures in the bucket, sign 15-minute links,
   send the page, and delete the pictures straight away;
4. read the presentation back and check every planned object arrived, on
   the right slide, with its text.

A picture Slides refuses is replaced by a marked box and the page sent
again, rather than losing the page. The report never carries a signed link
or anything Google echoed back about one.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path

import httpx

from .config import Settings
from .errors import ToolkitError
from .google import DRIVE, SEPARATOR, TRANSIENT, Google, clean_name, failed, save_report
from .model import Compatibility as C
from .model import warning
from .publisher import analysis_report
from .publisher_slides import CREATES, Plan, bind, check, missing_picture
from .storage import Bucket, MetadataCredentials, credentials
from .units import EMU_PER_POINT

SLIDES_API = "https://slides.googleapis.com/v1/presentations"
REFUSED_INDEX = re.compile(r"requests\[(\d+)\]")
ATTEMPTS = 3
MAX_REPLACED = 20  # pictures swapped for a marked box before a page is given up
PAGE_SIZE_TOLERANCE = 1.0  # points


class Refused(Exception):
    """Slides refused a page. `index` is the request it named, if any."""

    def __init__(self, status: int, index: int | None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.index = index


# ------------------------------------------------------------------ Google calls


def storage_client() -> httpx.AsyncClient:
    """The app's own connection for the bucket, apart from the person's."""
    return httpx.AsyncClient(timeout=60, follow_redirects=False)


async def _exists(google: Google, presentation: str, slide: str, object_id: str) -> bool:
    try:
        page = await google.request("GET", f"{SLIDES_API}/{presentation}/pages/{slide}")
    except ToolkitError:
        return False
    return f'"{object_id}"' in json.dumps(page)


async def send(google: Google, presentation: str, slide: str, requests: list[dict]) -> None:
    """One atomic batchUpdate, asked again only when it surely did not apply."""
    first = next(
        (next(iter(r.values()))[CREATES[k]] for r in requests for k in r if k in CREATES), None
    )
    delay = 1.0
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = await google.client.post(
                f"{SLIDES_API}/{presentation}:batchUpdate",
                headers=google.headers,
                json={"requests": requests},
            )
        except httpx.TransportError:
            response = None
        if response is not None and response.is_success:
            return
        if response is not None and response.status_code not in TRANSIENT:
            try:
                message = response.json().get("error", {}).get("message", "")
            except ValueError:
                message = ""
            found = REFUSED_INDEX.search(message)
            raise Refused(response.status_code, int(found.group(1)) if found else None)
        # A lost or failed reply can still mean the batch applied: look first.
        if first and await _exists(google, presentation, slide, first):
            return
        if attempt == ATTEMPTS:
            raise Refused(response.status_code if response is not None else 0, None)
        await asyncio.sleep(delay)
        delay *= 2


async def move(google: Google, file_id: str, folder: str) -> None:
    current = await google.request("GET", f"{DRIVE}/files/{file_id}", params={"fields": "parents"})
    await google.request(
        "PATCH",
        f"{DRIVE}/files/{file_id}",
        params={
            "addParents": folder,
            "removeParents": ",".join(current.get("parents", [])),
            "fields": "id",
        },
    )


# ------------------------------------------------------------------ one page


async def build_page(
    google: Google, bucket: Bucket, presentation: str, plan: Plan, index: int
) -> tuple[list[str], int]:
    """Sends one page. Returns the pictures replaced by a marked box, and how
    many stored copies could not be deleted (the lifecycle rule has them)."""
    stored: list[str] = []
    replaced: list[str] = []
    try:
        urls = {}
        for key in plan.keys_for(index):
            picture = plan.pictures[key]
            name = await bucket.upload(picture.path, picture.mime)
            stored.append(name)
            urls[key] = await bucket.sign(name)
        requests = bind(plan.pages[index], urls)
        while True:
            try:
                await send(google, presentation, plan.slides[index], requests)
                return replaced, 0
            except Refused as refusal:
                at = refusal.index
                if (
                    at is None
                    or at >= len(requests)
                    or "createImage" not in requests[at]
                    or len(replaced) >= MAX_REPLACED
                ):
                    raise
                image = requests[at]["createImage"]
                replaced.append(image["objectId"])
                requests = (
                    requests[:at]
                    + missing_picture(image["objectId"], image["elementProperties"])
                    + requests[at + 1 :]
                )
    finally:
        left = 0
        for name in stored:
            if not await bucket.delete(name):
                left += 1
        if left:
            plan.report.setdefault("storage", {})["notDeleted"] = (
                plan.report.get("storage", {}).get("notDeleted", 0) + left
            )


# ------------------------------------------------------------------ checking


def _walk(elements: list[dict]):
    for element in elements:
        yield element
        yield from _walk(element.get("elementGroup", {}).get("children", []))


def _text(element: dict) -> str:
    runs = element.get("shape", {}).get("text", {}).get("textElements", [])
    return "".join(r.get("textRun", {}).get("content", "") for r in runs)


def _squash(text: str) -> str:
    return "".join(text.split())


def verify(plan: Plan, presentation: dict, replaced: set[str]) -> list[dict]:
    """Every planned object on its own slide, the page size, and the text."""
    notes: list[dict] = []
    slides = {s["objectId"]: s for s in presentation.get("slides", [])}
    if list(slides) != plan.slides:
        notes.append(
            warning(
                "slides_differ",
                f"Expected {len(plan.slides)} slides in order; Google has {len(slides)}.",
                classification=C.UNSUPPORTED,
            )
        )
    missing: dict[int, int] = defaultdict(int)
    wrong_text = 0
    for number, (slide_id, requests) in enumerate(zip(plan.slides, plan.pages, strict=True)):
        found = {e["objectId"]: e for e in _walk(slides.get(slide_id, {}).get("pageElements", []))}
        expected_text: dict[str, str] = {}
        for request in requests:
            kind, body = next(iter(request.items()))
            if kind in CREATES and body[CREATES[kind]] not in found:
                missing[number + 1] += 1
            if kind == "insertText" and "cellLocation" not in body:
                expected_text[body["objectId"]] = (
                    expected_text.get(body["objectId"], "") + body["text"]
                )
        for object_id, text in expected_text.items():
            if object_id in found and object_id not in replaced:
                if _squash(_text(found[object_id])) != _squash(text):
                    wrong_text += 1
    if missing:
        pages = ", ".join(str(p) for p in sorted(missing))
        notes.append(
            warning(
                "objects_missing",
                f"{sum(missing.values())} planned item(s) are missing from Google Slides "
                f"(page {pages}).",
                classification=C.UNSUPPORTED,
            )
        )
    if wrong_text:
        notes.append(
            warning(
                "text_differs",
                f"The text in {wrong_text} text box(es) differs from the original.",
                classification=C.UNSUPPORTED,
            )
        )
    return notes


def page_size_note(plan: Plan, presentation: dict) -> dict | None:
    """Google may not keep a publication's size (PROJECT.md §14): say so if not."""
    wanted = plan.create["pageSize"]
    given = presentation.get("pageSize", {})

    def points(dimension: dict) -> float:
        value = float(dimension.get("magnitude", 0))
        return value / EMU_PER_POINT if dimension.get("unit") == "EMU" else value

    try:
        width, height = points(given["width"]), points(given["height"])
    except (KeyError, TypeError, ValueError):
        return None
    want_w, want_h = points(wanted["width"]), points(wanted["height"])
    if abs(width - want_w) <= PAGE_SIZE_TOLERANCE and abs(height - want_h) <= PAGE_SIZE_TOLERANCE:
        return None
    return warning(
        "page_size_changed",
        f"Google made the slides {width:.0f} × {height:.0f} pt instead of the original "
        f"{want_w:.0f} × {want_h:.0f} pt, so the layout will not line up.",
        classification=C.SUBSTITUTED,
    )


def summarise(plan: Plan) -> list[dict]:
    """The plan's per-element notes, one line per kind, for people to read."""
    grouped: dict[str, dict] = {}
    for line in plan.report.get("elements", []):
        for item in line.get("notes", []):
            entry = grouped.setdefault(
                item["code"],
                {"message": item["message"], "status": line["status"], "pages": set(), "count": 0},
            )
            entry["count"] += 1
            entry["pages"].add(line["pageIndex"] + 1)
    result = []
    for code, entry in grouped.items():
        pages = ", ".join(str(p) for p in sorted(entry["pages"]))
        result.append(
            warning(
                code,
                f"{entry['message']} ({entry['count']} on page {pages})",
                classification=entry["status"],
                count=entry["count"],
            )
        )
    for item in plan.report.get("warnings", []):
        result.append(warning(item["code"], item["message"], classification=C.SUBSTITUTED))
    return result


# ------------------------------------------------------------------ the conversion


async def convert(
    root: Path,
    manifest: dict,
    google: Google,
    progress: dict | None = None,
    original_name: str = "",
    settings: Settings | None = None,
) -> dict:
    report = progress if progress is not None else {}
    name = clean_name(original_name)
    output_name = f"{name}{SEPARATOR}converted" if name else "Converted publication"
    report.update(analysis_report(manifest))
    report.update(status="converting", outputs=[])
    replaced: set[str] = set()
    try:
        if settings is None or not settings.publisher_ready:
            raise ToolkitError(
                "not_convertible",
                "Converting Publisher files is not set up on this server.",
                501,
            )
        planned = root / "result" / "plan.json"
        if not planned.exists():
            raise ToolkitError(
                "plan_unavailable",
                "This Publisher file could be checked, but not prepared for Google Slides.",
                422,
            )
        plan = Plan.from_dict(json.loads(planned.read_text(encoding="utf-8")), root / "result")
        plan.create["title"] = output_name
        folder = await google.folder(output_name)
        report["folderUrl"] = "https://drive.google.com/drive/folders/" + folder
        # Never asked twice: a lost reply can still mean a presentation exists.
        created = await google.request("POST", SLIDES_API, json=plan.create)
        presentation = created["presentationId"]
        report["outputs"].append({"kind": "presentation", "id": presentation})
        report["presentationId"] = presentation
        report["url"] = f"https://docs.google.com/presentation/d/{presentation}/edit"
        await move(google, presentation, folder)
        size_note = page_size_note(plan, created)
        starting = [s["objectId"] for s in created.get("slides", [])]
        plan.setup += [{"deleteObject": {"objectId": s}} for s in starting]
        problems = check(plan, existing=starting)
        if problems:
            raise ToolkitError(
                "plan_invalid",
                "This file's conversion could not be prepared correctly.",
                500,
                detail=problems[0][:200],
            )
        try:
            await send(google, presentation, plan.slides[0], plan.setup)
        except Refused as refusal:
            raise ToolkitError(
                "google_failed",
                "Google could not create the slides.",
                502,
                detail=f"http_{refusal.status}",
            ) from None

        async with storage_client() as client:
            creds = credentials(client)
            signer = settings.publisher_signer
            if not signer and isinstance(creds, MetadataCredentials):
                signer = await creds.email()
            if not signer:
                raise ToolkitError(
                    "publisher_storage_unavailable",
                    "No account is set up to sign picture links (PUBLISHER_SIGNER).",
                    503,
                )
            bucket = Bucket(settings.publisher_bucket, signer, creds, client)
            failed_pages = []
            for index in range(len(plan.pages)):
                try:
                    swapped, _ = await build_page(google, bucket, presentation, plan, index)
                    replaced.update(swapped)
                except Refused:
                    failed_pages.append(index + 1)
        notes = summarise(plan)
        if size_note:
            notes.append(size_note)
        if replaced:
            notes.append(
                warning(
                    "pictures_refused",
                    f"Google Slides would not take {len(replaced)} picture(s); a marked box "
                    "shows where each one was.",
                    classification=C.UNSUPPORTED,
                )
            )
        if failed_pages:
            notes.append(
                warning(
                    "pages_failed",
                    "Google Slides refused page "
                    + ", ".join(map(str, failed_pages))
                    + ", which is left blank.",
                    classification=C.UNSUPPORTED,
                )
            )
        left = plan.report.get("storage", {}).get("notDeleted", 0)
        if left:
            notes.append(
                warning(
                    "pictures_not_deleted",
                    f"{left} temporary picture copies could not be deleted straight away; "
                    "the storage bucket removes them within a day.",
                )
            )
        readback = await google.request("GET", f"{SLIDES_API}/{presentation}")
        notes += verify(plan, readback, replaced)
        # The checker's notes about single elements are in the plan's own, with
        # what was done about them; keep only those about the whole document.
        report["warnings"] = [w for w in report.get("warnings", []) if "elementId" not in w] + notes
        report["conversion"] = {
            "statusCounts": plan.report.get("statusCounts", {}),
            "elements": plan.report.get("elements", []),
            "basis": "Read back from Google Slides after conversion.",
        }
        report["verification"] = "objects_page_size_and_text_checked"
        report["status"] = "completed_with_warnings" if notes else "completed"
    except ToolkitError as exc:
        failed(report, exc)
    except (KeyError, ValueError, OSError) as exc:
        failed(
            report,
            ToolkitError(
                "conversion_failed",
                "The conversion stopped unexpectedly.",
                500,
                detail=type(exc).__name__,
            ),
        )
    await save_report(root, report, google)
    return report
