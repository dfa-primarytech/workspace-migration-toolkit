"""Rich Text Format (.rtf) files, handed to Google's own import."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from workspace_toolkit import rtf
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.package import RTF, validate_upload_name
from workspace_toolkit.pipelines import resolve

from .test_web import configured, signed_client

SAMPLE = rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0\fs24 Conditional probability \b Q1\b0.\par}"


def write(tmp_path: Path, data: bytes = SAMPLE) -> Path:
    path = tmp_path / "source.rtf"
    path.write_bytes(data)
    return path


def analyse(path: Path, tmp_path: Path) -> dict:
    output = tmp_path / "result"
    output.mkdir(exist_ok=True)
    return rtf.analyse(path, output, Settings())


def test_an_rtf_file_is_a_supported_type():
    pipeline = resolve("Worksheet.RTF")
    assert pipeline.fmt is RTF
    assert pipeline.destination == "Google Docs"
    assert pipeline.source_name == "source.rtf"


@pytest.mark.parametrize("mime", ["application/rtf", "text/rtf", "application/octet-stream"])
def test_the_browsers_usual_types_for_rtf_are_accepted(mime):
    validate_upload_name("a.rtf", mime, RTF)


def test_an_rtf_is_checked_and_described(tmp_path):
    manifest = analyse(write(tmp_path), tmp_path)

    assert manifest["source"]["type"] == "rtf"
    report = rtf.analysis_report(manifest)
    assert report["sourceSha256"] == manifest["source"]["sha256"]
    assert [w["code"] for w in report["warnings"]] == ["rtf_not_repaired"]


def test_something_that_is_not_rtf_is_refused(tmp_path):
    with pytest.raises(ToolkitError) as error:
        analyse(write(tmp_path, b"just some plain text" * 50), tmp_path)
    assert error.value.code == "invalid_signature"


class FakeGoogle:
    def __init__(self, offers=True):
        self.offers = offers
        self.uploads = []

    async def request(self, method, url, **kwargs):
        mime = "application/vnd.google-apps.document"
        return {"importFormats": {"application/rtf": [mime]} if self.offers else {}}

    async def folder(self, name):
        return "folder1"

    async def upload(self, path, name, mime, parent, **kwargs):
        self.uploads.append((path.name, name, mime, parent, kwargs))
        return {"id": "doc1"}


def converted(tmp_path, google):
    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    shutil.copyfile(write(tmp_path), root / "source.rtf")
    manifest = rtf.analyse(root / "source.rtf", root / "result", Settings())
    return asyncio.run(rtf.convert(root, manifest, google, original_name="Worksheet"))


def test_the_rtf_is_handed_to_google_to_import_as_a_document(tmp_path):
    google = FakeGoogle()
    report = converted(tmp_path, google)

    ((path, _name, mime, parent, kwargs),) = google.uploads
    assert path == "source.rtf" and mime == "application/rtf" and parent == "folder1"
    assert kwargs["convert"] is True
    assert kwargs["target"] == "application/vnd.google-apps.document"
    assert report["status"] == "completed_with_warnings"
    assert report["url"].endswith("/doc1/edit")
    assert "rtf_not_repaired" in [w["code"] for w in report["warnings"]]


def test_an_account_google_does_not_convert_for_gets_a_plain_failure(tmp_path):
    google = FakeGoogle(offers=False)
    report = converted(tmp_path, google)

    assert report["status"] == "failed"
    assert google.uploads == []


def test_an_rtf_is_checked_through_the_app(tmp_path):
    client = signed_client(configured(temp_dir=str(tmp_path)))
    response = client.post(
        "/api/analyse",
        content=SAMPLE,
        headers={
            "Content-Type": "application/rtf",
            "X-Upload-Filename": "worksheet.rtf",
            "X-CSRF-Token": "test-csrf",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["warnings"][0]["code"] == "rtf_not_repaired"
    assert not list(tmp_path.iterdir()), "nothing is kept"
