from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import Settings
from .docs import render_path
from .docx import analyse as analyse_docx
from .errors import ToolkitError
from .pptx import analyse as analyse_pptx
from .pptx import render_path as render_pptx
from .xlsx import analyse as analyse_xlsx

# Deliberately not importing the pipelines registry: that pulls in the Google
# client, and this subprocess must never hold credentials or reach the network.
ANALYSERS = {"pptx": analyse_pptx, "docx": analyse_docx, "xlsx": analyse_xlsx, "xlsm": analyse_xlsx}


def main() -> None:
    source, output, config = map(Path, sys.argv[1:4])
    fmt = sys.argv[4] if len(sys.argv) > 4 else "pptx"
    settings = Settings(**json.loads(config.read_text(encoding="utf-8")))
    try:
        if sys.platform != "win32":
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
            resource.setrlimit(
                resource.RLIMIT_CPU, (settings.parser_timeout + 2, settings.parser_timeout + 2)
            )
        ANALYSERS[fmt](source, output, settings)
        if fmt == "docx":
            # Rewriting happens here too: it is the same bounded, credential-free
            # sandbox that already parses the untrusted package.
            report = render_path(source, output / "converted.docx", settings)
            (output / "render.json").write_text(json.dumps(report), encoding="utf-8")
        elif fmt == "pptx":
            report = render_pptx(source, output / "converted.pptx", settings)
            (output / "render.json").write_text(json.dumps(report), encoding="utf-8")
    except ToolkitError as exc:
        (output / "error.json").write_text(
            json.dumps({"code": exc.code, "message": exc.message, "status": exc.status}),
            encoding="utf-8",
        )
        raise SystemExit(2) from None
    except Exception:
        (output / "error.json").write_text(
            json.dumps(
                {
                    "code": "parse_failed",
                    "message": "The file could not be analysed.",
                    "status": 400,
                }
            ),
            encoding="utf-8",
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
