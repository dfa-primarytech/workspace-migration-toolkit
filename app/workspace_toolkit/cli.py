from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from .config import Settings
from .errors import ToolkitError
from .jobs import preflight, workspace
from .package import PPTX_MIME, validate_upload_name
from .pptx import analysis_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse one PowerPoint without Google access.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        validate_upload_name(args.source.name, PPTX_MIME)
        if args.output.exists():
            raise ToolkitError("output_exists", "The output directory already exists.")
        if args.source.stat().st_size > settings.max_upload_bytes:
            raise ToolkitError("upload_too_large", "This file exceeds the upload size limit.")
        with workspace(settings) as (_, root):
            shutil.copyfile(args.source, root / "source.pptx")
            manifest = asyncio.run(preflight(root, settings))
            shutil.copytree(root / "result", args.output)
            report = analysis_report(manifest)
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "pages": report["pages"],
                        "assetCounts": report["assetCounts"],
                    }
                )
            )
    except (ToolkitError, OSError) as exc:
        print(json.dumps({"error": exc.code if isinstance(exc, ToolkitError) else "file_error"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
