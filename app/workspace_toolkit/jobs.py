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
from .package import PPTX, Format


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
    source = root / ("source" + fmt.suffix)
    # A larger file gets proportionally longer; the worker's own CPU limit is
    # set from the same figure, so the two cannot disagree.
    timeout = settings.parser_timeout_for(source.stat().st_size if source.exists() else 0)
    limits = {
        k: v
        for k, v in asdict(settings).items()
        if k.startswith(("max_", "worker_memory_")) or k in {"entry_scale", "expanded_scale"}
    }
    limits["parser_timeout"] = timeout
    config.write_text(json.dumps(limits), encoding="utf-8")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "workspace_toolkit.worker",
        str(source),
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
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise ToolkitError("parser_timeout", "This file took too long to analyse.", 422) from None
    except asyncio.CancelledError:
        # Not a slow file: the client went away, or the whole job ran out of
        # time. Stop the worker and let the cancellation through, so the job
        # timeout is reported as itself rather than as a parser timeout.
        if process.returncode is None:
            process.kill()
        await asyncio.shield(process.wait())
        raise
    if process.returncode:
        error = output / "error.json"
        if error.exists():
            data = json.loads(error.read_text(encoding="utf-8"))
            raise ToolkitError(data["code"], data["message"], data["status"])
        raise ToolkitError("parse_failed", "The file could not be analysed.")
    return json.loads((output / "manifest.json").read_text(encoding="utf-8"))
