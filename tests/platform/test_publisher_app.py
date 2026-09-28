"""A Publisher file can be checked in the app (DECISIONS.md, 2026-09-28).

The real reader is the native publisher-parser; these tests drive the app's
side of it -- the subprocess, its outcomes, the report -- through a stand-in
that writes the same bundle files. The real binary is exercised by the
publisher-parser CI job and the app image build.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.fonts import compatibility
from workspace_toolkit.package import PUB, validate_upload_name
from workspace_toolkit.pipelines import describe
from workspace_toolkit.publisher import analyse, analysis_report
from workspace_toolkit.web import create_app

from .test_web import SESSION, configured

PUB_MIME = "application/x-mspublisher"


def document() -> dict:
    """A two-page A5 publication, shaped like the parser's document.json."""

    def page(index: int, elements: list[dict]) -> dict:
        return {
            "id": f"page_{index + 1:04d}",
            "index": index,
            "kind": "page",
            "width": 420.944882,
            "height": 595.275591,
            "unit": "pt",
            "elements": elements,
        }

    text = {
        "id": "el_000001",
        "type": "text",
        "warnings": [],
        "compatibility": {"status": "NATIVE"},
    }
    image = {
        "id": "el_000002",
        "type": "image",
        "warnings": [],
        "compatibility": {"status": "NATIVE"},
    }
    path = {
        "id": "el_000003",
        "type": "path",
        "warnings": [{"code": "path-flattened", "message": "A drawn path is kept as a picture."}],
        "compatibility": {"status": "FLATTENED"},
    }
    return {
        "schemaVersion": "1.0.0",
        "source": {"type": "publisher", "filename": "booklet.pub", "sha256": "ab" * 32},
        "fonts": [{"family": "SassoonPrimaryInfant"}, {"family": "Calibri"}],
        "pages": [page(0, [text, image]), page(1, [path])],
        "warnings": [],
        "limitations": [{"code": "no-lists", "message": "Lists are not recoverable."}],
        "truncation": {"truncated": False, "reason": None},
    }


STAND_IN = """
import json, sys, time
from pathlib import Path
mode = {mode!r}
args = sys.argv[1:]
source, bundle = Path(args[-2]), Path(args[-1])
bundle.mkdir(parents=True)
if mode == "slow":
    time.sleep(30)
report = {{"status": "ok", "failureCode": None, "diagnostics": []}}
if mode in ("refuse", "fail"):
    report = {{"status": "failed", "failureCode": "unsupported-document" if mode == "refuse" else "parse-failed"}}
(bundle / "report.json").write_text(json.dumps(report))
if mode == "refuse":
    sys.exit(2)
if mode == "fail":
    sys.exit(1)
(bundle / "document.json").write_text(json.dumps({document}))
(bundle / "assets.json").write_text(json.dumps({{"assets": [{{"mimeType": "image/png"}}, {{"mimeType": "image/jpeg"}}]}}))
"""


def stand_in(tmp_path: Path, mode: str = "ok") -> str:
    script = tmp_path / f"parser_{mode}.py"
    script.write_text(STAND_IN.format(mode=mode, document=document()), encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / f"parser_{mode}.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / f"parser_{mode}"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return str(launcher)


def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.pub"
    path.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + os.urandom(512))
    return path


# ------------------------------------------------------------------ the format


@pytest.mark.parametrize(
    "mime", [PUB_MIME, "application/vnd.ms-publisher", "application/octet-stream"]
)
def test_a_pub_is_accepted_under_the_types_browsers_send(mime):
    validate_upload_name("booklet.pub", mime, PUB)


def test_a_pub_with_the_wrong_type_is_refused():
    with pytest.raises(ToolkitError):
        validate_upload_name("booklet.pub", "text/plain", PUB)


def test_the_browser_is_told_a_pub_can_be_checked_but_not_yet_converted():
    formats = {f["extension"]: f for f in describe()}
    assert formats[".pub"]["convertible"] is False
    assert formats[".pptx"]["convertible"] is True


def test_sassoon_as_publisher_spells_it_becomes_andika():
    for name in ("SassoonPrimaryInfant", "SassoonPrimaryType"):
        result = compatibility(name)
        assert result["status"] == "SUBSTITUTED" and result["replacement"] == "Andika", name
        assert result["manualReview"] is False


# -------------------------------------------------------------- the analysis


def test_a_publisher_file_is_read_and_summarised(tmp_path):
    output = tmp_path / "result"
    output.mkdir()
    settings = Settings(publisher_parser=stand_in(tmp_path))
    manifest = analyse(source(tmp_path), output, settings)
    assert json.loads((output / "manifest.json").read_text())["source"]["sha256"] == "ab" * 32

    report = analysis_report(manifest)
    assert report["pages"] == 2
    assert report["dimensionsPt"] == {"width": 420.944882, "height": 595.275591}
    assert report["elementCounts"] == {"text": 1, "image": 1, "path": 1}
    assert report["assetCounts"] == {"image": 2}
    fonts = {f["name"]: f for f in report["fonts"]}
    assert fonts["SassoonPrimaryInfant"]["replacement"] == "Andika"
    codes = [w["code"] for w in report["warnings"]]
    assert "path-flattened" in codes and "publisher_check_only" in codes
    assert report["limitations"][0]["code"] == "no-lists"


@pytest.mark.parametrize(
    "mode, code, status",
    [("refuse", "unsupported_document", 400), ("fail", "parse_failed", 422)],
)
def test_a_file_the_reader_refuses_says_so_plainly(tmp_path, mode, code, status):
    output = tmp_path / "result"
    output.mkdir()
    with pytest.raises(ToolkitError) as error:
        analyse(source(tmp_path), output, Settings(publisher_parser=stand_in(tmp_path, mode)))
    assert (error.value.code, error.value.status) == (code, status)
    assert "Publisher" in error.value.message or "read" in error.value.message


def test_a_server_without_the_reader_says_so(tmp_path):
    output = tmp_path / "result"
    output.mkdir()
    settings = Settings(publisher_parser=str(tmp_path / "missing"))
    with pytest.raises(ToolkitError) as error:
        analyse(source(tmp_path), output, settings)
    assert error.value.code == "publisher_unavailable"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="the Windows stand-in runs through cmd.exe, whose child outlives the kill; "
    "the real parser is one process, and Linux runs this",
)
def test_a_reader_that_hangs_is_stopped(tmp_path):
    output = tmp_path / "result"
    output.mkdir()
    settings = Settings(publisher_parser=stand_in(tmp_path, "slow"), parser_timeout=2)
    began = time.monotonic()
    with pytest.raises(ToolkitError) as error:
        analyse(source(tmp_path), output, settings)
    assert error.value.code == "parser_timeout"
    assert time.monotonic() - began < 20


# ------------------------------------------------------------- through the app


def client_for(tmp_path, parser):
    settings = configured(publisher_parser=parser)
    app = create_app(settings)
    client = TestClient(app, base_url=settings.base_url)
    cookie = {"access_token": "t", "expires": time.time() + 3600, "csrf": "c"}
    client.cookies.set(SESSION, app.state.auth.seal(cookie))
    return client


HEADERS = {"Content-Type": PUB_MIME, "X-Upload-Filename": "booklet.pub", "X-CSRF-Token": "c"}


def test_checking_a_pub_through_the_app(tmp_path):
    client = client_for(tmp_path, stand_in(tmp_path))
    response = client.post("/api/analyse", content=source(tmp_path).read_bytes(), headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["pages"] == 2


def test_converting_a_pub_is_refused_before_the_upload(tmp_path):
    client = client_for(tmp_path, stand_in(tmp_path))
    headers = {**HEADERS, "X-Source-Sha256": "ab" * 32}
    response = client.post("/api/convert", content=b"never read", headers=headers)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_convertible"


def test_the_setting_reaches_the_worker():
    assert replace(Settings(), publisher_parser="/x").publisher_parser == "/x"
