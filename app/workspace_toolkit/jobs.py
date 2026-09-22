from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .config import Settings
from .errors import ToolkitError


@contextmanager
def workspace(settings: Settings):
    with TemporaryDirectory(prefix="wmt-", dir=settings.temp_dir) as directory:
        root = Path(directory)
        yield uuid4().hex, root


async def preflight(root: Path, settings: Settings) -> dict:
    output = root / "result"
    output.mkdir()
    # Worker receives limits only, never OAuth credentials or session keys.
    config = root / "limits.json"
    limits = {
        k: v for k, v in asdict(settings).items() if k.startswith("max_") or k == "parser_timeout"
    }
    config.write_text(json.dumps(limits), encoding="utf-8")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "workspace_toolkit.worker",
        str(root / "source.pptx"),
        str(output),
        str(config),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env={
            k: v
            for k, v in os.environ.items()
            if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
        },
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=settings.parser_timeout)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise ToolkitError(
            "parser_timeout", "This presentation took too long to analyse.", 422
        ) from None
    if process.returncode:
        error = output / "error.json"
        if error.exists():
            data = json.loads(error.read_text(encoding="utf-8"))
            raise ToolkitError(data["code"], data["message"], data["status"])
        raise ToolkitError("parse_failed", "The presentation could not be analysed.")
    return json.loads((output / "manifest.json").read_text(encoding="utf-8"))
