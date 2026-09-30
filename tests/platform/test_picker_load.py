"""The Google Picker loader retries after a failed load (#132).

A failed script or picker load used to stay cached as a rejected promise, so
"Add from Drive" kept failing until the page was reloaded. The page's own
loadPicker() is run under Node against a fake page; skipped without Node.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

APP_JS = Path(__file__).parents[2] / "app" / "workspace_toolkit" / "static" / "app.js"
HARNESS = Path(__file__).with_name("picker_harness.js")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="needs Node to run app.js")


def run(scenario: str) -> dict:
    done = subprocess.run(  # nosec B603 -- fixed arguments, no shell
        [str(NODE), str(HARNESS), str(APP_JS), scenario],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(done.stdout)


def test_a_script_that_fails_to_load_is_tried_again():
    result = run("network")
    assert (result["first"], result["second"]) == ("failed", "loaded")
    assert result["scripts"] == 2
    assert result["removed"] == [True, False]  # the failed script is taken away


def test_a_picker_that_fails_to_load_is_tried_again_without_a_second_script():
    result = run("picker")
    assert (result["first"], result["second"]) == ("failed", "loaded")
    assert result["scripts"] == 1 and result["loads"] == 2


def test_a_load_in_progress_or_done_is_shared():
    result = run("shared")
    assert result["same"] and result["again"] and result["first"] == "loaded"
    assert result["scripts"] == 1
