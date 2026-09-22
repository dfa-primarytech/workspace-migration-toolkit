import asyncio
import json

import httpx
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.google import Google, convert, verify
from workspace_toolkit.package import PPTX_MIME
from workspace_toolkit.pptx import analyse


def fake_presentation():
    return {
        "pageSize": {
            "width": {"magnitude": 840, "unit": "PT"},
            "height": {"magnitude": 595, "unit": "PT"},
        },
        "slides": [
            {
                "pageElements": [
                    {"shape": {"text": {"textElements": [{"textRun": {"content": text}}]}}}
                ]
            }
            for text in ["Hello school", "Last slide"]
        ],
    }


def test_verify_detects_missing_text_and_dimensions(pptx, tmp_path):
    manifest = analyse(pptx, tmp_path / "result")
    good = verify(manifest, fake_presentation())
    assert [w["code"] for w in good] == ["visual_review_required"]
    damaged = fake_presentation()
    damaged["slides"][0]["pageElements"] = []
    damaged["pageSize"]["width"]["magnitude"] = 720
    assert {w["code"] for w in verify(manifest, damaged)} >= {"text_mismatch", "page_size_changed"}


def test_native_conversion_assets_and_report(pptx, tmp_path):
    root = tmp_path / "job"
    root.mkdir()
    (root / "source.pptx").write_bytes(pptx.read_bytes())
    manifest = analyse(pptx, root / "result")
    uploads = []

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-token"
        if request.url.path.endswith("/about"):
            return httpx.Response(
                200,
                json={"importFormats": {PPTX_MIME: ["application/vnd.google-apps.presentation"]}},
            )
        if request.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"id": "folder1"})
        if request.method == "POST" and request.url.path == "/upload/drive/v3/files":
            uploads.append(json.loads(request.content))
            return httpx.Response(
                200, headers={"Location": "https://www.googleapis.com/upload/session"}
            )
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "uploaded" + str(len(uploads))})
        if request.url.host == "slides.googleapis.com":
            return httpx.Response(200, json=fake_presentation())
        raise AssertionError(str(request.url))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await convert(root, manifest, Google("test-token", client))

    report = asyncio.run(run())
    assert report["status"] == "completed_with_warnings"
    assert report["verification"] == "page_size_count_and_text_checked"
    assert len(report["assetOutputs"]) == 3
    assert uploads[0]["mimeType"] == "application/vnd.google-apps.presentation"
    assert {u["mimeType"] for u in uploads} >= {"video/mp4", "audio/wav", "application/json"}
    assert all(u["parents"] == ["folder1"] for u in uploads)
    assert report["reportUrl"].startswith("https://drive.google.com/")


def test_partial_failure_keeps_recovery_links(pptx, tmp_path):
    manifest = analyse(pptx, tmp_path / "result")

    class FailedGoogle:
        async def request(self, *a, **kw):
            return {"importFormats": {PPTX_MIME: ["application/vnd.google-apps.presentation"]}}

        async def folder(self):
            return "partial-folder"

        async def upload(self, *a, **kw):
            raise ToolkitError("upload_uncertain", "Check the conversion folder before retrying.")

    report = asyncio.run(convert(tmp_path, manifest, FailedGoogle()))
    assert report["status"] == "failed_with_partial_outputs"
    assert "partial-folder" in report["folderUrl"]
    assert report["verification"] == "incomplete"


def test_upload_does_not_follow_untrusted_location(tmp_path):
    path = tmp_path / "asset"
    path.write_bytes(b"data")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"Location": "https://evil.invalid/steal"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            try:
                await Google("private-token", client).upload(path, "asset", "video/mp4", "folder")
            except ToolkitError as error:
                assert error.code == "upload_uncertain"
            else:
                raise AssertionError("Untrusted upload accepted")

    asyncio.run(run())
    assert len(requests) == 1
