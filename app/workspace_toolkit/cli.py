"""Convert one file locally, with no Google access and no credentials.

This is how a real document gets through the converter without a Cloud
project: the same sandboxed worker the server uses, driven from a terminal.
The output can then be uploaded by hand to see what the importer makes of it.

It handles every format the pipeline registry knows, because the registry is
the one place that decides. It used to be PowerPoint only -- the registry
arrived with the DOCX port and the worker learned to use it, but this did not,
so there was no way to run a Word document through the converter by hand at
all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from . import pipelines
from .config import Settings
from .errors import ToolkitError
from .jobs import preflight, workspace
from .package import validate_upload_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            f"Analyse and convert one file without Google access. Handles {pipelines.SUPPORTED}."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="Directory to create; must not exist.")
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        pipeline = pipelines.resolve(args.source.name)
        validate_upload_name(args.source.name, pipeline.fmt.mime, pipeline.fmt)
        if args.output.exists():
            raise ToolkitError("output_exists", "The output directory already exists.")
        if args.source.stat().st_size > settings.max_upload_bytes:
            raise ToolkitError("upload_too_large", "This file exceeds the upload size limit.")

        with workspace(settings) as (_, root):
            # Copied under the pipeline's own name: the source's filename is
            # never used inside the job directory.
            shutil.copyfile(args.source, root / pipeline.source_name)
            manifest = asyncio.run(preflight(root, settings, pipeline.fmt))
            shutil.copytree(root / "result", args.output)

        report = pipeline.analysis_report(manifest)
        converted = args.output / ("converted" + pipeline.fmt.suffix)
        summary = {
            "status": report.get("status"),
            "kind": pipeline.kind,
            "destination": pipeline.destination,
            "pages": report.get("pages"),
            "elementCounts": report.get("elementCounts"),
            "fonts": report.get("fonts"),
        }
        # The rewritten package is the point of running this, so say where it
        # is rather than leaving it to be found.
        if converted.exists():
            summary["converted"] = str(converted)
        render = args.output / "render.json"
        if render.exists():
            conversion = json.loads(render.read_text(encoding="utf-8"))
            # "tokens" is every word in the document. It exists so the importer
            # can be checked for silent loss, and it belongs in the job
            # directory, not on someone's terminal or in their shell history.
            # The rest of the report is counts, which say what happened without
            # saying what the document is about.
            summary["conversion"] = {k: v for k, v in conversion.items() if k != "tokens"}
        print(json.dumps({k: v for k, v in summary.items() if v is not None}, indent=2))
    except (ToolkitError, OSError) as exc:
        print(json.dumps({"error": exc.code if isinstance(exc, ToolkitError) else "file_error"}))
        raise SystemExit(1) from None
