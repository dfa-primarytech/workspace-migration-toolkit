"""TEMPORARY diagnostic for PR #89: why the worker refuses the picture-test deck
on Linux. Prints the real traceback and peak memory under the worker's limits.
Remove once understood."""

from __future__ import annotations

import subprocess
import sys
import textwrap

from .test_pictures import deck, encode, photo, pic

SCRIPT = textwrap.dedent(
    """
    import resource, sys, traceback
    from pathlib import Path
    from workspace_toolkit.config import Settings
    from workspace_toolkit.pptx import analyse, render_path
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    settings = Settings()
    limit = settings.worker_memory_for(source.stat().st_size)
    if sys.argv[3] == "limited":
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    try:
        analyse(source, out, settings)
        render_path(source, out / "converted.pptx", settings)
        print("OK")
    except BaseException:
        traceback.print_exc()
    status = Path("/proc/self/status").read_text()
    print([l for l in status.splitlines() if l.startswith(("VmPeak", "VmHWM"))], "cap MiB", limit >> 20)
    """
)


def test_diagnose_the_worker_on_this_deck(tmp_path):
    if sys.platform == "win32":
        return
    source = deck(tmp_path, {"photo.png": encode(photo(), "PNG")}, pic("rId1", 4, 8 / 3))
    for mode in ("unlimited", "limited"):
        out = tmp_path / mode
        out.mkdir()
        run = subprocess.run(  # noqa: S603 -- fixed argv, temporary diagnostic
            [sys.executable, "-c", SCRIPT, str(source), str(out), mode],
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(f"--- {mode}: rc={run.returncode}\n{run.stdout}\n{run.stderr}")
    raise AssertionError("diagnostic output above")
