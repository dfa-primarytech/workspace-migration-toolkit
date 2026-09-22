from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import Settings
from .errors import ToolkitError
from .pptx import analyse


def main() -> None:
    source, output, config = map(Path, sys.argv[1:4])
    settings = Settings(**json.loads(config.read_text(encoding="utf-8")))
    try:
        if sys.platform != "win32":
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
            resource.setrlimit(
                resource.RLIMIT_CPU, (settings.parser_timeout + 2, settings.parser_timeout + 2)
            )
        analyse(source, output, settings)
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
                    "message": "The presentation could not be analysed.",
                    "status": 400,
                }
            ),
            encoding="utf-8",
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
