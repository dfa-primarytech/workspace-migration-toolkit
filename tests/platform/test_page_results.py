"""What the page tells a teacher when a file isn't converted.

Two gaps from the live test (2026-10-01): a workbook kept for moving by hand
was shown as "Converted." with only a Folder link, and a dropped connection
showed the browser's own "Failed to fetch". The page's own request() and
convertAll() are run under Node against fakes; skipped without Node.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

APP_JS = Path(__file__).parents[2] / "app" / "workspace_toolkit" / "static" / "app.js"
HARNESS = Path(__file__).with_name("results_harness.js")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="needs Node to run app.js")


def run(scenario: str) -> dict:
    done = subprocess.run(  # noqa: S603  # nosec B603 -- fixed argv, no shell
        [str(NODE), str(HARNESS), str(APP_JS), scenario],
        capture_output=True,
        text=True,
        encoding="utf-8",  # the page's curly apostrophes, on Windows too
        timeout=30,
        check=True,
    )
    return json.loads(done.stdout)


def test_a_file_with_nothing_to_open_is_not_called_converted():
    result = run("kept")
    assert result["row"] == "Not converted: it has macros, which Google Sheets can’t run. [Folder]"
    assert result["status"] == "0 converted, 1 couldn’t be."


def test_a_converted_file_still_offers_its_link():
    result = run("converted")
    assert result["row"] == "[Open in Google Sheets] · [Folder]"
    assert result["status"] == "Converted."


def test_no_answer_at_all_is_explained_in_plain_words():
    assert run("offline")["message"] == (
        "Couldn’t reach the converter. Check your connection and try again."
    )
