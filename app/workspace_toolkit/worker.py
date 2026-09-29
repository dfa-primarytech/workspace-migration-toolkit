from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from .config import Settings
from .docs import render_path
from .docx import analyse as analyse_docx
from .errors import ToolkitError
from .package import FORMATS
from .pictures import compress
from .pptx import analyse as analyse_pptx
from .pptx import render_path as render_pptx
from .publisher import analyse as analyse_pub
from .xlsx import analyse as analyse_xlsx

# Deliberately not importing the pipelines registry: that pulls in the Google
# client, and this subprocess must never hold credentials or reach the network.
ANALYSERS: dict[str, Callable[..., object]] = {
    "pptx": analyse_pptx,
    "docx": analyse_docx,
    "pub": analyse_pub,
    "xlsx": analyse_xlsx,
    "xlsm": analyse_xlsx,
}


def limit(name: str, value: int) -> None:
    """Caps this process, never above a cap it already has.

    A process can lower its own limits but never raise them, so asking for
    more than an inherited hard limit fails -- and since the memory cap grows
    with the file, a large file would then fail where a small one passed. An
    environment that is already stricter keeps its own, stricter limit.
    """
    if sys.platform == "win32":  # no OS resource limits there
        return
    import resource

    kind = getattr(resource, name)
    _, hard = resource.getrlimit(kind)
    if hard != resource.RLIM_INFINITY:
        value = min(value, hard)
    resource.setrlimit(kind, (value, value))


def main() -> None:
    source, output, config = map(Path, sys.argv[1:4])
    fmt = sys.argv[4] if len(sys.argv) > 4 else "pptx"
    smaller_pictures = len(sys.argv) > 5 and sys.argv[5] == "compress-pictures"
    settings = Settings(**json.loads(config.read_text(encoding="utf-8")))
    try:
        if sys.platform != "win32":
            limit(
                "RLIMIT_AS",
                settings.worker_memory_for(source.stat().st_size),
            )
            limit("RLIMIT_CPU", settings.parser_timeout + 2)
        ANALYSERS[fmt](source, output, settings)
        if fmt == "docx":
            # Rewriting happens here too: it is the same bounded, credential-free
            # sandbox that already parses the untrusted package.
            report = render_path(source, output / "converted.docx", settings)
            (output / "render.json").write_text(json.dumps(report), encoding="utf-8")
        elif fmt == "pptx":
            report = render_pptx(source, output / "converted.pptx", settings)
            (output / "render.json").write_text(json.dumps(report), encoding="utf-8")
        if smaller_pictures:
            # Only when asked for, and never fatal: a failure here leaves the
            # converted file as it was, with its pictures at full size.
            converted = output / ("converted." + fmt)
            try:
                result = compress(converted, settings, FORMATS["." + fmt])
            except Exception:
                converted.with_name(converted.name + ".smaller").unlink(missing_ok=True)
                result = {"failed": True, "picturesCompressed": []}
            (output / "pictures.json").write_text(json.dumps(result), encoding="utf-8")
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
