"""Rich Text Format (.rtf) files, imported by Google's own converter.

Like a legacy .doc (see doc.py), nothing here repairs the layout: the file is
checked to be RTF and Google's import makes the Google Doc. The report says so,
so nobody takes it for the repaired conversion .docx gets. RTF has no password
protection, so there is nothing to unlock.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import Settings
from .doc import import_document
from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning

RTF_MIME = "application/rtf"
SIGNATURE = rb"{\rtf"


def analyse(source: Path, output: Path, settings: Settings | None = None) -> dict:
    """Checks `source` is an RTF file and writes `output/manifest.json`."""
    settings = settings or Settings()
    size = source.stat().st_size
    if settings.max_upload_bytes is not None and size > settings.max_upload_bytes:
        raise ToolkitError("upload_too_large", "This file exceeds the upload size limit.", 413)
    if size > settings.max_expanded_bytes:
        raise ToolkitError("upload_too_large", "This file is too large to convert here.", 413)
    data = source.read_bytes()
    # Word tolerates a little before the opening brace; so does a BOM.
    if SIGNATURE not in data[:64]:
        raise ToolkitError("invalid_signature", "This is not a valid .rtf file.")
    manifest = {
        "schemaVersion": "1.0",
        "source": {"type": "rtf", "sha256": hashlib.sha256(data).hexdigest()},
        "bytes": size,
    }
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def analysis_report(manifest: dict) -> dict:
    """The "Check file" summary: all there is to say before Google opens it."""
    return {
        "schemaVersion": "1.0",
        "status": "analysed",
        "sourceSha256": manifest["source"]["sha256"],
        "warnings": [
            warning(
                "rtf_not_repaired",
                "This Rich Text Format file is converted by Google's own import, without "
                "the layout repairs .docx files get. Check pictures, tables and equations "
                "afterwards.",
                classification=C.UNSUPPORTED,
            )
        ],
        "verification": "not_converted",
        "classificationBasis": "An .rtf file is imported by Google as it is.",
    }


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
        source="source.rtf",
        mime=RTF_MIME,
        describe=analysis_report,
    )
