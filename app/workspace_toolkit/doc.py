"""Legacy Word 97-2003 (.doc) files, imported by Google's own converter.

Nothing here repairs the layout: there is no .doc reader beyond checking the
file is a real Word document. Google's import is what makes the Google Doc, and
the report says so, so nobody takes it for the repaired conversion .docx gets.
A protected file is unlocked first (see protected.py, run in the worker).
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import olefile  # type: ignore[import-untyped, unused-ignore]

from .config import Settings
from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning

DOC_MIME = "application/msword"
ENCRYPTED_FLAG = 0x0100  # in the FIB's flags word


def analyse(source: Path, output: Path, settings: Settings | None = None) -> dict:
    """Checks `source` is a Word document and writes `output/manifest.json`."""
    settings = settings or Settings()
    size = source.stat().st_size
    if settings.max_upload_bytes is not None and size > settings.max_upload_bytes:
        raise ToolkitError("upload_too_large", "This file exceeds the upload size limit.", 413)
    if size > settings.max_expanded_bytes:
        raise ToolkitError("upload_too_large", "This file is too large to convert here.", 413)
    if not olefile.isOleFile(str(source)):
        raise ToolkitError("invalid_signature", "This is not a valid .doc file.")
    try:
        with olefile.OleFileIO(str(source)) as ole:
            if not ole.exists("WordDocument"):
                raise ToolkitError("invalid_signature", "This is not a Word document.")
            header = ole.openstream("WordDocument").read(12)
    except ToolkitError:
        raise
    except Exception:  # noqa: BLE001
        raise ToolkitError("invalid_signature", "This is not a valid .doc file.") from None
    flags = struct.unpack_from("<H", header, 10)[0] if len(header) >= 12 else 0
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {
        "schemaVersion": "1.0",
        "source": {"type": "doc", "sha256": digest},
        "bytes": size,
        "stillProtected": bool(flags & ENCRYPTED_FLAG),
    }
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def analysis_report(manifest: dict) -> dict:
    """The "Check file" summary: all there is to say before Google opens it."""
    return {
        "schemaVersion": "1.0",
        "status": "analysed",
        "sourceSha256": manifest["source"]["sha256"],
        "warnings": [_unrepaired()],
        "verification": "not_converted",
        "classificationBasis": "A legacy .doc is imported by Google as it is.",
    }


def _unrepaired() -> dict:
    return warning(
        "doc_not_repaired",
        "This older Word format is converted by Google's own import, without the layout "
        "repairs .docx files get. Check text boxes, pictures and tables afterwards.",
        classification=C.UNSUPPORTED,
    )


async def convert(
    root: Path,
    manifest: dict,
    google,
    progress: dict | None = None,
    original_name: str = "",
    settings: Settings | None = None,
) -> dict:
    """Uploads the file for Google to import as a document."""
    return await import_document(
        root,
        manifest,
        google,
        progress,
        original_name,
        source="source.doc",
        mime=DOC_MIME,
        describe=analysis_report,
    )


async def import_document(
    root: Path,
    manifest: dict,
    google,
    progress: dict | None,
    original_name: str,
    *,
    source: str,
    mime: str,
    describe,
) -> dict:
    """Hands `root/source` to Google to import as a Google Doc (shared with .rtf)."""
    # imported here to avoid a cycle
    from .google import DOCS_MIME, DRIVE, SEPARATOR, clean_name

    name = clean_name(original_name)
    output_name = f"{name}{SEPARATOR}converted" if name else "Converted document"
    report = progress if progress is not None else {}
    report.update(describe(manifest))
    report.update(status="converting", outputs=[], assetOutputs=[])
    try:
        formats = await google.request("GET", DRIVE + "/about", params={"fields": "importFormats"})
        if DOCS_MIME not in formats.get("importFormats", {}).get(mime, []):
            raise ToolkitError(
                "conversion_unavailable",
                "Google does not currently offer this conversion for this account.",
                422,
            )
        folder = await google.folder(output_name)
        report["folderUrl"] = "https://drive.google.com/drive/folders/" + folder
        uploaded = await google.upload(
            root / source, output_name, mime, folder, convert=True, target=DOCS_MIME
        )
        report["outputs"].append({"kind": "document", "id": uploaded["id"]})
        report["documentId"] = uploaded["id"]
        report["url"] = "https://docs.google.com/document/d/" + uploaded["id"] + "/edit"
        report["verification"] = "imported_by_google"
        report["status"] = "completed_with_warnings"
    except ToolkitError as exc:
        report["status"] = "failed_with_partial_outputs" if report.get("folderUrl") else "failed"
        report.setdefault("warnings", []).append(
            warning(exc.code, exc.message, classification=C.UNSUPPORTED)
        )
        report["verification"] = "incomplete"
    return report
