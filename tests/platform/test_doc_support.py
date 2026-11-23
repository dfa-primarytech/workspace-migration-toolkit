"""Legacy .doc files, and password-protected Office files.

The two fixtures were saved by Word from a synthetic page of text, with the
document's personal information removed; `protected.doc` opens with the
password below.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from workspace_toolkit import doc, protected
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.package import DOC, validate_upload_name
from workspace_toolkit.pipelines import resolve

DATA = Path(__file__).parent / "data"
PASSWORD = "swordfish"  # nosec B105  # pragma: allowlist secret -- a synthetic test file


def copy(tmp_path: Path, name: str) -> Path:
    target = tmp_path / "source.doc"
    shutil.copyfile(DATA / name, target)
    return target


def analyse(path: Path, tmp_path: Path) -> dict:
    output = tmp_path / "result"
    output.mkdir(exist_ok=True)
    return doc.analyse(path, output, Settings())


# --- the format is on offer -------------------------------------------------


def test_a_doc_file_is_a_supported_type():
    pipeline = resolve("Observation report.DOC")
    assert pipeline.fmt is DOC
    assert pipeline.destination == "Google Docs"
    assert pipeline.source_name == "source.doc"


@pytest.mark.parametrize("mime", ["application/msword", "application/octet-stream", ""])
def test_the_browsers_usual_types_for_a_doc_are_accepted(mime):
    if mime == "":
        with pytest.raises(ToolkitError):
            validate_upload_name("a.doc", mime, DOC)
    else:
        validate_upload_name("a.doc", mime, DOC)


# --- reading it -------------------------------------------------------------


def test_a_plain_doc_is_checked_and_described(tmp_path):
    manifest = analyse(copy(tmp_path, "plain.doc"), tmp_path)

    assert manifest["source"]["type"] == "doc"
    assert manifest["stillProtected"] is False
    report = doc.analysis_report(manifest)
    assert report["sourceSha256"] == manifest["source"]["sha256"]
    assert [w["code"] for w in report["warnings"]] == ["doc_not_repaired"]


def test_something_that_is_not_a_word_document_is_refused(tmp_path):
    fake = tmp_path / "source.doc"
    fake.write_bytes(b"not a compound file at all" * 100)

    with pytest.raises(ToolkitError) as error:
        analyse(fake, tmp_path)
    assert error.value.code == "invalid_signature"


# --- protection -------------------------------------------------------------


def test_a_file_without_protection_is_left_alone(tmp_path):
    path = copy(tmp_path, "plain.doc")
    before = path.read_bytes()

    assert protected.unlock(path, None) is False
    assert protected.unlock(path, "anything") is False
    assert path.read_bytes() == before


def test_a_protected_file_asks_for_its_password(tmp_path):
    with pytest.raises(ToolkitError) as error:
        protected.unlock(copy(tmp_path, "protected.doc"), None)
    assert error.value.code == "password_required"
    assert error.value.status == 422


def test_the_wrong_password_is_said_to_be_wrong(tmp_path):
    path = copy(tmp_path, "protected.doc")
    before = path.read_bytes()

    with pytest.raises(ToolkitError) as error:
        protected.unlock(path, "not-it")
    assert error.value.code == "wrong_password"
    assert path.read_bytes() == before, "the file is not changed by a wrong guess"


def test_the_right_password_unlocks_it_and_it_then_reads_as_a_document(tmp_path):
    path = copy(tmp_path, "protected.doc")
    assert analyse_still_locked(path, tmp_path) is True

    assert protected.unlock(path, PASSWORD) is True

    assert analyse_still_locked(path, tmp_path) is False


def analyse_still_locked(path: Path, tmp_path: Path) -> bool:
    return analyse(path, tmp_path)["stillProtected"]


def test_the_password_is_nowhere_in_what_is_kept(tmp_path):
    path = copy(tmp_path, "protected.doc")
    protected.unlock(path, PASSWORD)
    manifest = analyse(path, tmp_path)

    kept = json.dumps([manifest, doc.analysis_report(manifest)])
    assert PASSWORD not in kept


# --- converting -------------------------------------------------------------


class FakeGoogle:
    def __init__(self, offers=True):
        self.offers = offers
        self.uploads = []

    async def request(self, method, url, **kwargs):
        mime = "application/vnd.google-apps.document"
        return {"importFormats": {"application/msword": [mime]} if self.offers else {}}

    async def folder(self, name):
        return "folder1"

    async def upload(self, path, name, mime, parent, **kwargs):
        self.uploads.append((path.name, name, mime, parent, kwargs))
        return {"id": "doc1"}


def converted(tmp_path, google):
    root = tmp_path / "job"
    root.mkdir()
    shutil.copyfile(DATA / "plain.doc", root / "source.doc")
    (root / "result").mkdir()
    manifest = doc.analyse(root / "source.doc", root / "result", Settings())
    return asyncio.run(doc.convert(root, manifest, google, original_name="Visit record"))


def test_the_doc_is_handed_to_google_to_import_as_a_document(tmp_path):
    google = FakeGoogle()
    report = converted(tmp_path, google)

    ((path, name, mime, parent, kwargs),) = google.uploads
    assert path == "source.doc" and mime == "application/msword" and parent == "folder1"
    assert kwargs["convert"] is True
    assert kwargs["target"] == "application/vnd.google-apps.document"
    assert report["status"] == "completed_with_warnings"
    assert report["url"].endswith("/doc1/edit")
    assert report["verification"] == "imported_by_google"
    assert "doc_not_repaired" in [w["code"] for w in report["warnings"]]


def test_an_account_google_does_not_convert_for_gets_a_plain_failure(tmp_path):
    google = FakeGoogle(offers=False)
    report = converted(tmp_path, google)

    assert report["status"] == "failed"
    assert google.uploads == []
    assert "conversion_unavailable" in [w["code"] for w in report["warnings"]]


# --- through the app --------------------------------------------------------

from .test_web import configured, signed_client  # noqa: E402


def post(client, name, password=None):
    headers = {
        "Content-Type": "application/msword",
        "X-Upload-Filename": "report.doc",
        "X-CSRF-Token": "test-csrf",
    }
    if password is not None:
        headers["X-File-Password"] = password
    return client.post("/api/analyse", content=(DATA / name).read_bytes(), headers=headers)


def test_a_doc_is_checked_through_the_app(tmp_path):
    client = signed_client(configured(temp_dir=str(tmp_path)))
    response = post(client, "plain.doc")

    assert response.status_code == 200, response.text
    assert response.json()["warnings"][0]["code"] == "doc_not_repaired"
    assert not list(tmp_path.iterdir()), "nothing is kept"


def test_a_protected_doc_asks_for_its_password_through_the_app(tmp_path):
    client = signed_client(configured(temp_dir=str(tmp_path)))
    response = post(client, "protected.doc")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "password_required"


def test_the_password_in_the_request_opens_the_file_and_is_never_echoed(tmp_path):
    client = signed_client(configured(temp_dir=str(tmp_path)))

    wrong = post(client, "protected.doc", "nope")
    assert wrong.json()["error"]["code"] == "wrong_password"

    right = post(client, "protected.doc", PASSWORD)
    assert right.status_code == 200, right.text
    assert PASSWORD not in right.text and PASSWORD not in wrong.text
    assert not list(tmp_path.iterdir())
