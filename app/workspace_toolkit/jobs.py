from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .config import Settings
from .errors import ToolkitError
from .package import PPTX, Format


def sweep_stale_workspaces(
    settings: Settings, older_than_seconds: int = 24 * 60 * 60, now: float | None = None
) -> int:
    """Remove abandoned job directories after an interrupted process.

    This is an explicit startup/scheduled hook, not a background thread. It
    only considers directories with TemporaryDirectory's ``wmt-`` prefix
    directly beneath the configured temporary root.
    """
    base = Path(settings.temp_dir or tempfile.gettempdir()).resolve()
    cutoff = (time.time() if now is None else now) - older_than_seconds
    removed = 0
    for candidate in base.glob("wmt-*"):
        resolved = candidate.resolve()
        if resolved.parent != base or not resolved.is_dir() or resolved.stat().st_mtime > cutoff:
            continue
        shutil.rmtree(resolved)
        removed += 1
    return removed


@contextmanager
def workspace(settings: Settings):
    with TemporaryDirectory(prefix="wmt-", dir=settings.temp_dir) as directory:
        root = Path(directory)
        yield uuid4().hex, root


async def preflight(root: Path, settings: Settings, fmt: Format = PPTX) -> dict:
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
        str(root / ("source" + fmt.suffix)),
        str(output),
        str(config),
        fmt.key,
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
        raise ToolkitError("parser_timeout", "This file took too long to analyse.", 422) from None
    if process.returncode:
        error = output / "error.json"
        if error.exists():
            data = json.loads(error.read_text(encoding="utf-8"))
            raise ToolkitError(data["code"], data["message"], data["status"])
        raise ToolkitError("parse_failed", "The file could not be analysed.")
    return json.loads((output / "manifest.json").read_text(encoding="utf-8"))
