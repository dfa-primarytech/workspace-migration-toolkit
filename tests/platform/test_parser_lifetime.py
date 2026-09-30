"""Stopping a job stops the Publisher parser too (#130).

The worker runs the parser and waits for it. Killing only the worker, on the
job's own timeout or when the job was cancelled, left the parser running on
its own. A stand-in parser here records its process id and hangs; after the
job stops, nothing may be left running under that id.

Linux only, as production is: Windows has no process groups to stop, and the
app is only developed there.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.jobs import preflight, workspace
from workspace_toolkit.package import PUB

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")

HANG = """#!/bin/sh
echo $$ > "{pid}"
exec sleep 60
"""


def hanging_parser(folder: Path) -> tuple[str, Path]:
    pid = folder / "parser.pid"
    script = folder / "parser"
    script.write_text(HANG.format(pid=pid), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script), pid


def running(pid: int) -> bool:
    """Alive and not merely waiting to be reaped."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        state = next(
            (line for line in status.read_text().splitlines() if line.startswith("State:")), ""
        )
        return "zombie" not in state
    return True


def gone_soon(pid: int) -> bool:
    for _ in range(50):
        if not running(pid):
            return True
        time.sleep(0.1)
    return False


def started(pid_file: Path) -> int:
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text().strip():
            return int(pid_file.read_text())
        time.sleep(0.1)
    raise AssertionError("the stand-in parser never started")


def job(tmp_path: Path, parser_timeout: int):
    parser, pid_file = hanging_parser(tmp_path)
    settings = replace(
        Settings(), temp_dir=str(tmp_path), publisher_parser=parser, parser_timeout=parser_timeout
    )
    return settings, pid_file


def source(root: Path) -> None:
    (root / "source.pub").write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + bytes(512))


def test_a_parser_timeout_leaves_no_parser_running(tmp_path):
    # The job's own timeout starts first, so it fires before the worker's
    # timeout for the parser does: the case that orphaned it.
    settings, pid_file = job(tmp_path, parser_timeout=4)
    with workspace(settings) as (_, root):
        source(root)
        with pytest.raises(ToolkitError) as error:
            asyncio.run(preflight(root, settings, PUB))
    assert error.value.code == "parser_timeout"
    assert gone_soon(started(pid_file)), "the parser outlived its job"


def test_a_cancelled_job_leaves_no_parser_running(tmp_path):
    settings, pid_file = job(tmp_path, parser_timeout=30)

    async def cancel_once_started(root):
        task = asyncio.create_task(preflight(root, settings, PUB))
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with workspace(settings) as (_, root):
        source(root)
        asyncio.run(cancel_once_started(root))
    assert gone_soon(started(pid_file)), "the parser outlived its job"
