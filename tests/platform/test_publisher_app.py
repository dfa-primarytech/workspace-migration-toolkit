"""A Publisher file can be checked in the app (DECISIONS.md, 2026-09-28).

The real reader is the native publisher-parser; these tests drive the app's
side of it -- the subprocess, its outcomes, the report -- through a stand-in
that writes the same bundle files. The real binary is exercised by the
publisher-parser CI job and the app image build.
"""

from __future__ import annotations

import asyncio
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
from workspace_toolkit.jobs import preflight
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

    def element(eid: str, kind: str, page_index: int, z: int, **extra) -> dict:
        return {
            "id": eid,
            "type": kind,
            "pageIndex": page_index,
            "bounds": {"x": 20, "y": 20 + 60 * z, "width": 200, "height": 50, "unit": "pt"},
            "zIndex": z,
            "parentId": None,
            "visible": True,
            "source": {"properties": {}, "styleProperties": {"draw:fill": "none"}},
            "warnings": [],
            "compatibility": {"status": "NATIVE"},
            **extra,
        }

    run = {
        "text": "Hello",
        "items": [{"kind": "text", "value": "Hello"}],
        "style": {
            "fontFamily": "SassoonPrimaryInfant",
            "fontSizePoints": 12,
            "bold": False,
            "italic": False,
            "underline": None,
            "color": "#000000",
        },
    }
    text = element(
        "el_000001",
        "text",
        0,
        0,
        paragraphs=[{"style": {"alignment": "left", "lineHeight": None}, "runs": [run]}],
    )
    image = element(
        "el_000002",
        "image",
        0,
        1,
        image={"assetId": "asset_0001", "polygon": [], "path": []},
    )
    rule = [
        {"action": "M", "properties": {"svg:x": "0.5in", "svg:y": "1in"}},
        {"action": "L", "properties": {"svg:x": "3in", "svg:y": "1in"}},
    ]
    path = element(
        "el_000003",
        "path",
        1,
        0,
        bounds=None,
        geometry={"shapeKind": "path", "points": [], "path": rule},
        warnings=[{"code": "path-flattened", "message": "A drawn path is kept as a picture."}],
        compatibility={"status": "FLATTENED"},
    )
    path["source"]["styleProperties"] = {"draw:stroke": "solid", "svg:stroke-color": "#8064a2"}
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
failures = {{"refuse": ("unsupported-document", 2), "fail": ("parse-failed", 1),
            "oom": ("out-of-memory", 4), "crash": ("internal-error", 4)}}
if mode in failures:
    report = {{"status": "failed", "failureCode": failures[mode][0]}}
(bundle / "report.json").write_text(json.dumps(report))
if mode in failures:
    sys.exit(failures[mode][1])
(bundle / "document.json").write_text(json.dumps({document}))
(bundle / "assets.json").write_text(json.dumps({{"assets": [{{"id": "asset_0001", "filename": "assets/" + "0" * 64 + ".png", "mimeType": "image/png"}}, {{"id": "asset_0002", "filename": "assets/" + "1" * 64 + ".jpg", "mimeType": "image/jpeg"}}]}}))
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


def test_a_pub_converts_only_where_a_picture_bucket_is_set_up():
    plain = {f["extension"]: f for f in describe(Settings())}
    assert plain[".pub"]["convertible"] is False
    assert plain[".pptx"]["convertible"] is True
    ready = {f["extension"]: f for f in describe(Settings(publisher_bucket="b"))}
    assert ready[".pub"]["convertible"] is True


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
    # The reader's own notes are kept for support, not listed for staff.
    assert "path-flattened" not in [w["code"] for w in report["warnings"]]
    assert "path-flattened" in [w["code"] for w in report["technicalNotes"]]
    assert report["limitations"][0]["code"] == "no-lists"


@pytest.mark.parametrize(
    "mode, code, status",
    [
        ("refuse", "unsupported_document", 400),
        ("fail", "parse_failed", 422),
        # The parser's last-resort report (#129): not a bad file.
        ("oom", "out_of_memory", 422),
        ("crash", "internal_error", 500),
    ],
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


@pytest.mark.parametrize("check_only", [True, False])
def test_checking_a_pub_does_not_plan_its_slides(tmp_path, check_only):
    # Planning drew PUB-002's 47 shapes in the check too, and the check timed
    # out: it is done when converting, where the plan is used.
    root = tmp_path / "job"
    root.mkdir()
    (root / "source.pub").write_bytes(source(tmp_path).read_bytes())
    settings = Settings(publisher_parser=stand_in(tmp_path), temp_dir=str(tmp_path))
    asyncio.run(preflight(root, settings, PUB, check_only=check_only))
    planned = {p.name for p in (root / "result").iterdir()} & {"plan.json", "plan-error.json"}
    assert bool(planned) is not check_only
