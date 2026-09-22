from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning
from .package import PPTX_MIME
from .pptx import analysis_report

SLIDES_MIME = "application/vnd.google-apps.presentation"
DRIVE = "https://www.googleapis.com/drive/v3"


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
            ) from exc

    async def folder(self) -> str:
        result = await self.request(
            "POST",
            DRIVE + "/files",
            json={"name": "Workspace conversion", "mimeType": "application/vnd.google-apps.folder"},
            params={"fields": "id"},
        )
        folder_id = result.get("id")
        if not isinstance(folder_id, str) or not folder_id:
            raise ToolkitError(
                "google_failed", "Google could not create the conversion folder.", 502
            )
        return folder_id

    async def upload(
        self, path: Path, name: str, mime: str, parent: str, convert: bool = False
    ) -> dict:
        metadata = {"name": name, "mimeType": SLIDES_MIME if convert else mime, "parents": [parent]}
        try:
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
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # Never retry creation blindly: a lost response can still mean success.
            raise ToolkitError(
                "upload_uncertain",
                "A Google upload failed or its result is uncertain. Check the conversion folder before retrying.",
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


async def convert(
    root: Path,
    manifest: dict,
    google: Google,
    progress: dict | None = None,
    output_name: str = "Converted presentation",
) -> dict:
    report = progress if progress is not None else {}
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
        folder = await google.folder()
        report["folderUrl"] = "https://drive.google.com/drive/folders/" + folder
        result = await google.upload(
            root / "source.pptx", output_name, PPTX_MIME, folder, convert=True
        )
        report["outputs"].append({"kind": "presentation", "id": result["id"]})
        report["presentationId"] = result["id"]
        report["url"] = "https://docs.google.com/presentation/d/" + result["id"] + "/edit"
        # Preserve every extracted asset privately, including audio/video that the
        # native importer might omit. No public permissions or automatic execution.
        for asset in manifest["assets"].values():
            uploaded = await google.upload(
                root / "result" / asset["path"], asset["id"], asset["mimeType"], folder
            )
            report["assetOutputs"].append(
                {
                    "assetId": asset["id"],
                    "kind": asset["kind"],
                    "driveFileId": uploaded["id"],
                    "url": "https://drive.google.com/file/d/" + uploaded["id"] + "/view",
                }
            )
        presentation = await google.inspect(result["id"])
        report["warnings"].extend(verify(manifest, presentation))
        report["verification"] = "page_size_count_and_text_checked"
        report["status"] = "completed_with_warnings"
    except ToolkitError as exc:
        report["status"] = "failed_with_partial_outputs" if report.get("folderUrl") else "failed"
        report["warnings"].append(warning(exc.code, exc.message, classification=C.UNSUPPORTED))
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
