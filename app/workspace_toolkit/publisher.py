"""Publisher `.pub` files: run the native parser, and report what it found.

A `.pub` is not a zip package, so nothing in `package.py` applies. The
`publisher-parser` binary (native/pub-parser, libmspub) reads it and writes a
bundle -- document.json, assets.json, report.json and the extracted assets --
described in docs/publisher-parser.md. This module runs it inside the
analysis worker, with a hard timeout of its own because the parser's
`--max-seconds` cannot stop a hang inside libmspub, and turns the bundle into
the manifest the rest of the app expects.

Converting to Google Slides is not part of this step (see DECISIONS.md,
2026-09-28): a `.pub` can be checked, and the check says so.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 -- fixed argv, no shell, a binary we build
from collections import Counter
from pathlib import Path

from .config import Settings
from .errors import ToolkitError
from .fonts import catalogue
from .model import Compatibility as C
from .model import warning

# What the parser's failure codes mean, in words a member of staff can act on.
REFUSALS = {
    "unsupported-document": "This does not look like a Publisher file that can be read.",
    "input-empty": "Please choose a file that is not empty.",
    "input-unreadable": "This file could not be read.",
    "input-too-large": "This file is too large to read.",
    "parse-failed": "This Publisher file could not be read completely.",
}


def _run(settings: Settings, source: Path, bundle: Path) -> int:
    binary = Path(settings.publisher_parser)
    if not binary.is_file():
        raise ToolkitError(
            "publisher_unavailable", "Publisher files cannot be read on this server.", 503
        )
    size = source.stat().st_size
    # Its own limit is only a backstop: this timeout is the one that holds.
    budget = max(5, settings.parser_timeout - 5)
    try:
        run = subprocess.run(  # noqa: S603  # nosec B603 -- fixed argv, no shell
            [
                str(binary),
                # The file is already on disk and within any configured limit
                # (issue #36); the parser's own caps scale with it the same way.
                "--max-input-bytes",
                str(size + 1),
                "--max-total-asset-bytes",
                str(settings.expanded_limit(size)),
                "--max-asset-bytes",
                str(settings.entry_limit(size)),
                "--max-seconds",
                str(budget),
                str(source),
                str(bundle),
            ],
            capture_output=True,
            timeout=settings.parser_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ToolkitError("parser_timeout", "This file took too long to analyse.", 422) from None
    return run.returncode


def analyse(source: Path, output: Path, settings: Settings) -> dict:
    """Parses `source` into `output/bundle` and writes `output/manifest.json`."""
    bundle = output / "bundle"
    code = _run(settings, source, bundle)
    report_path = bundle / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    if code != 0:
        failure = report.get("failureCode") or "parse-failed"
        raise ToolkitError(
            failure.replace("-", "_"),
            REFUSALS.get(failure, "This Publisher file could not be read."),
            422 if failure == "parse-failed" else 400,
        )
    document = json.loads((bundle / "document.json").read_text(encoding="utf-8"))
    assets = json.loads((bundle / "assets.json").read_text(encoding="utf-8"))
    manifest = {
        "schemaVersion": "1.0",
        "source": {**document["source"], "type": "pub"},
        "document": document,
        "assets": assets,
        "report": report,
        "bundle": "bundle",
    }
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def analysis_report(manifest: dict) -> dict:
    """The "Check file" summary for a Publisher file."""
    document = manifest["document"]
    pages = [p for p in document["pages"] if p.get("kind", "page") == "page"]
    elements = [e for page in pages for e in page.get("elements", [])]
    assets = manifest["assets"].get("assets", [])
    families = {font["family"] for font in document.get("fonts", []) if font.get("family")}
    notes = []
    for note in document.get("warnings", []):
        notes.append(warning(note["code"], note["message"], classification=C.UNSUPPORTED))
    for page in pages:
        for element in page.get("elements", []):
            for note in element.get("warnings", []):
                notes.append(
                    warning(
                        note["code"],
                        note["message"],
                        pageIndex=page["index"],
                        elementId=element["id"],
                        classification=element.get("compatibility", {}).get(
                            "status", C.UNSUPPORTED
                        ),
                    )
                )
    for diagnostic in manifest.get("report", {}).get("diagnostics", []):
        if diagnostic.get("severity") in {"warning", "error"}:
            notes.append(
                warning(diagnostic["code"], diagnostic["message"], classification=C.UNSUPPORTED)
            )
    if document.get("truncation", {}).get("truncated"):
        notes.append(
            warning(
                "publisher_truncated",
                "This file is larger than the reader's limits, so only part of it was read.",
                classification=C.UNSUPPORTED,
            )
        )
    notes.append(
        warning(
            "publisher_check_only",
            "Publisher files can be checked here. Converting them to Google Slides is "
            "not available yet.",
            classification=C.IGNORED,
        )
    )
    first = pages[0] if pages else {}
    return {
        "schemaVersion": "1.0",
        "status": "analysed",
        "sourceSha256": manifest["source"]["sha256"],
        "pages": len(pages),
        "dimensionsPt": {"width": first.get("width"), "height": first.get("height")},
        "elementCounts": dict(Counter(e["type"] for e in elements)),
        "assetCounts": dict(
            Counter(a.get("mimeType", "").split("/", 1)[0] or "file" for a in assets)
        ),
        "fonts": catalogue(families),
        "warnings": notes,
        "limitations": document.get("limitations", []),
        "verification": "not_converted",
        "classificationBasis": "Preflight candidates, not verified Google compatibility.",
    }


async def convert(*args, **kwargs) -> dict:
    """Not yet: the Slides renderer is the next step (DECISIONS.md, 2026-09-28)."""
    raise ToolkitError(
        "publisher_convert_unavailable",
        "Converting Publisher files to Google Slides is not available yet.",
        501,
    )
