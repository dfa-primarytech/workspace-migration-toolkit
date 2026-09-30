"""A file Google turns down for its size says which limit (#36).

Google's published conversion limits are 50 MB to Docs and 100 MB to Slides or
Sheets. A larger file is warned about before converting; if Google then turns
it down, the reason given for the failure names the limit instead of a generic
upload failure. Nothing here talks to Google.
"""

from __future__ import annotations

from workspace_toolkit.package import PPTX_MIME

from .test_web import configured, signed_client


def _convert_failing(monkeypatch, pptx, *, limit, failure):
    """Converts through the route with a pipeline that stops on `failure`."""
    from dataclasses import replace

    from workspace_toolkit import web
    from workspace_toolkit.pipelines import resolve

    async def analysed(root, settings, fmt, **options):
        (root / "result").mkdir(parents=True, exist_ok=True)
        return {"source": {"sha256": "abc"}}

    async def converted(root, manifest, google, progress, original_name=""):
        report = {"status": "completed", "warnings": []}
        if failure:
            report = {
                "status": "failed_with_partial_outputs",
                "folderUrl": "https://drive.google.com/drive/folders/folder-1",
                "warnings": [{"code": failure, "message": "A Google upload failed."}],
                "stoppedBecause": "A Google upload failed.",
            }
        return report

    async def upload(self, path, name, mime, parent, **options):
        return {"id": "report-1"}

    monkeypatch.setattr(web, "preflight", analysed)
    monkeypatch.setattr(web, "resolve", lambda name: replace(resolve("x.pptx"), convert=converted))
    monkeypatch.setattr(web, "IMPORT_LIMITS", {"pptx": ("Google Slides", limit)})
    monkeypatch.setattr(web.Google, "upload", upload)
    response = signed_client(configured()).post(
        "/api/convert",
        content=pptx.read_bytes(),
        headers={
            "Content-Type": PPTX_MIME,
            "X-Upload-Filename": "x.pptx",
            "X-CSRF-Token": "test-csrf",
            "X-Source-SHA256": "abc",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_file_google_turns_down_for_its_size_says_which_limit(monkeypatch, pptx):
    report = _convert_failing(monkeypatch, pptx, limit=100, failure="upload_uncertain")
    why = report["stoppedBecause"]
    assert why.startswith("Google didn't convert it.")
    assert "Google's limit for converting to Google Slides is" in why
    assert "Make pictures smaller" in why


def test_a_failure_for_another_reason_is_not_blamed_on_size(monkeypatch, pptx):
    report = _convert_failing(monkeypatch, pptx, limit=100, failure="session_expired")
    assert report["stoppedBecause"] == "A Google upload failed."


def test_a_file_within_the_limit_keeps_its_own_reason(monkeypatch, pptx):
    report = _convert_failing(monkeypatch, pptx, limit=10**12, failure="upload_uncertain")
    assert report["stoppedBecause"] == "A Google upload failed."


def test_a_large_file_that_converts_is_only_warned_about(monkeypatch, pptx):
    report = _convert_failing(monkeypatch, pptx, limit=100, failure=None)
    assert "stoppedBecause" not in report
    (note,) = [w for w in report["warnings"] if w["code"] == "beyond_import_limit"]
    assert note["product"] == "Google Slides"
