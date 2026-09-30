"""The Drive picker opens at My Drive, with shared drives beside it.

Its one view had no parent, and Google then lists every folder in Drive at
once, nested ones included, with no way to tell where each is: in the live
test the first screen was a wall of folders from a downloaded website. The
page's own openPicker() is run under Node against a fake Picker; skipped
without Node.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

APP_JS = Path(__file__).parents[2] / "app" / "workspace_toolkit" / "static" / "app.js"
HARNESS = Path(__file__).with_name("picker_views_harness.js")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="needs Node to run app.js")


def built() -> dict:
    done = subprocess.run(  # noqa: S603  # nosec B603 -- fixed argv, no shell
        [str(NODE), str(HARNESS), str(APP_JS)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(done.stdout)


def test_the_picker_starts_at_my_drive():
    views = built()["views"]
    assert views[0].get("setParent") == "root"


def test_shared_drives_have_their_own_tab():
    views = built()["views"]
    assert any(v.get("setEnableDrives") is True for v in views)


def test_every_view_offers_only_convertible_files_and_opens_folders():
    result = built()
    assert result["added"] == len(result["views"]) >= 2
    for view in result["views"]:
        assert view["setMimeTypes"] == "a/b,c/d"
        assert view["setIncludeFolders"] is True
        assert view["setSelectFolderEnabled"] is False
    assert "multiselect" in result["features"]
