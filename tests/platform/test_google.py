import asyncio
import io
import json
import zipfile

import httpx
import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.google import Google, convert, google_text, verify
from workspace_toolkit.package import PPTX_MIME
from workspace_toolkit.pptx import analyse, render_path


def fake_presentation():
    return {
        "pageSize": {
            "width": {"magnitude": 840, "unit": "PT"},
            "height": {"magnitude": 595, "unit": "PT"},
        },
        "slides": [
            {
                "pageElements": [
                    {"shape": {"text": {"textElements": [{"textRun": {"content": text}}]}}},
                    {"image": {"contentUrl": "redacted"}},
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


def test_verify_detects_missing_images_tables_and_charts(pptx, tmp_path):
    manifest = analyse(pptx, tmp_path / "result")
    source = manifest["pages"][0]
    source["elements"].extend(
        [
            {"type": "table", "paragraphs": [], "warnings": [], "id": "table"},
            {"type": "chart", "paragraphs": [], "warnings": [], "id": "chart"},
        ]
    )
    converted = fake_presentation()
    converted["slides"][0]["pageElements"] = converted["slides"][0]["pageElements"][:1]
    findings = verify(manifest, converted)
    missing = {
        finding["objectType"]: (finding["sourceCount"], finding["convertedCount"])
        for finding in findings
        if finding["code"] == "object_count_changed"
    }
    assert missing == {"image": (1, 0), "table": (1, 0), "chart": (1, 0)}


def test_verify_counts_nested_google_objects_and_separates_table_cells(pptx, tmp_path):
    manifest = analyse(pptx, tmp_path / "result")
    manifest["pages"][0]["elements"].append(
        {"type": "table", "paragraphs": [], "warnings": [], "id": "table"}
    )
    converted = fake_presentation()
    converted["slides"][0]["pageElements"].append(
        {
            "elementGroup": {
                "children": [
                    {"image": {"contentUrl": "redacted"}},
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "text": {
                                                "textElements": [{"textRun": {"content": "one"}}]
                                            }
                                        },
                                        {
                                            "text": {
                                                "textElements": [{"textRun": {"content": "two"}}]
                                            }
                                        },
                                    ]
                                }
                            ]
                        }
                    },
                ]
            }
        }
    )
    assert google_text(converted["slides"][0]["pageElements"][-1]) == "one two"
    assert not [
        finding
        for finding in verify(manifest, converted)
        if finding["code"] == "object_count_changed"
    ]


def test_native_conversion_assets_and_report(pptx, tmp_path):
    root = tmp_path / "job"
    root.mkdir()
    (root / "source.pptx").write_bytes(pptx.read_bytes())
    manifest = analyse(pptx, root / "result")
    rendered = render_path(pptx, root / "result" / "converted.pptx", Settings())
    (root / "result" / "render.json").write_text(json.dumps(rendered), encoding="utf-8")
    uploads = []
    bodies = []

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
            bodies.append(request.content)
            return httpx.Response(200, json={"id": "uploaded" + str(len(uploads))})
        if request.url.host == "slides.googleapis.com":
            return httpx.Response(200, json=fake_presentation())
        raise AssertionError(str(request.url))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await convert(
                root,
                manifest,
                Google("test-token", client),
                output_name="School assembly – converted",
            )

    report = asyncio.run(run())
    assert report["status"] == "completed_with_warnings"
    assert report["verification"] == "page_size_count_and_text_checked"
    assert len(report["assetOutputs"]) == 3
    assert uploads[0]["mimeType"] == "application/vnd.google-apps.presentation"
    assert uploads[0]["name"] == "School assembly – converted"
    assert {u["mimeType"] for u in uploads} >= {"video/mp4", "audio/wav", "application/json"}
    assert all(u["parents"] == ["folder1"] for u in uploads)
    assert report["reportUrl"].startswith("https://drive.google.com/")
    assert report["conversion"]["fontSubstitutions"] == rendered["fontSubstitutions"]
    with zipfile.ZipFile(io.BytesIO(bodies[0])) as converted:
        # Calibri is present in Google Docs, so it is preserved rather than
        # swapped for Carlito; only genuinely absent families are replaced.
        assert b'typeface="Calibri"' in converted.read("ppt/slides/slide2.xml")


def test_partial_failure_keeps_recovery_links(pptx, tmp_path):
    manifest = analyse(pptx, tmp_path / "result")

    class FailedGoogle:
        async def request(self, *a, **kw):
            return {"importFormats": {PPTX_MIME: ["application/vnd.google-apps.presentation"]}}

        async def folder(self, job_name="Conversion"):
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


def test_google_rejects_malformed_success_responses(tmp_path):
    path = tmp_path / "asset"
    path.write_bytes(b"data")

    async def run_request():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
        ) as client:
            with pytest.raises(ToolkitError) as error:
                await Google("test-token", client).request("GET", "https://www.googleapis.com/x")
            assert error.value.code == "google_failed"

    async def run_folder():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ) as client:
            with pytest.raises(ToolkitError) as error:
                await Google("test-token", client).folder()
            assert error.value.code == "google_failed"

    def upload_handler(request):
        if request.method == "POST":
            return httpx.Response(
                200, headers={"Location": "https://www.googleapis.com/upload/session"}
            )
        return httpx.Response(200, json={})

    async def run_upload():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upload_handler)) as client:
            with pytest.raises(ToolkitError) as error:
                await Google("test-token", client).upload(
                    path, "asset", "application/octet-stream", "folder"
                )
            assert error.value.code == "upload_uncertain"

    asyncio.run(run_request())
    asyncio.run(run_folder())
    asyncio.run(run_upload())


def transport_calls(responses):
    """A Drive stand-in that replays `responses` and records what it was asked."""
    calls = []

    def handler(request):
        calls.append(request)
        return responses[min(len(calls) - 1, len(responses) - 1)](request)

    return calls, httpx.MockTransport(handler)


def json_body(request):
    return json.loads(request.content.decode())


def test_every_job_lands_in_one_shared_library_folder():
    """A new top-level folder per conversion buries the person's Drive.

    Measured against real use: each run created another "Workspace conversion"
    at the root. There should be one library, and a dated subfolder per job.
    """
    existing = [
        lambda r: httpx.Response(200, json={"files": [{"id": "library-1"}]}),
        lambda r: httpx.Response(200, json={"id": "job-1"}),
    ]

    async def run():
        calls, transport = transport_calls(existing)
        async with httpx.AsyncClient(transport=transport) as client:
            job = await Google("test-token", client).folder("Worksheet – converted")
        assert job == "job-1"
        assert calls[0].method == "GET", "the library must be looked for before creating one"
        created = [c for c in calls if c.method == "POST"]
        assert len(created) == 1, "an existing library must be reused, never duplicated"
        body = json_body(created[0])
        assert body["parents"] == ["library-1"], "the job folder belongs inside the library"
        assert body["name"].startswith("Worksheet – converted ("), body["name"]

    asyncio.run(run())


def test_the_library_folder_is_created_once_when_it_is_missing():
    first_run = [
        lambda r: httpx.Response(200, json={"files": []}),
        lambda r: httpx.Response(200, json={"id": "library-new"}),
        lambda r: httpx.Response(200, json={"id": "job-1"}),
    ]

    async def run():
        calls, transport = transport_calls(first_run)
        async with httpx.AsyncClient(transport=transport) as client:
            await Google("test-token", client).folder("Worksheet")
        created = [json_body(c) for c in calls if c.method == "POST"]
        assert "parents" not in created[0], "the library itself sits at the top level"
        assert created[0]["name"] == "Workspace conversions"
        assert created[1]["parents"] == ["library-new"]

    asyncio.run(run())


def test_a_throttled_asset_copy_is_retried_until_it_lands(tmp_path, monkeypatch):
    """Drive throttles a burst of uploads. 65 images in one worksheet is a burst."""
    path = tmp_path / "asset"
    path.write_bytes(b"data")
    waits = []

    async def no_waiting(seconds):
        waits.append(seconds)

    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", no_waiting)
    attempts = []

    def handler(request):
        if request.method == "POST":
            attempts.append(request)
            if len(attempts) < 3:
                return httpx.Response(429, json={"error": "rateLimitExceeded"})
            return httpx.Response(
                200, headers={"Location": "https://www.googleapis.com/upload/session"}
            )
        return httpx.Response(200, json={"id": "asset-1"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Google("test-token", client).upload(
                path, "asset", "image/png", "folder", retry=True
            )

    assert asyncio.run(run())["id"] == "asset-1"
    assert len(attempts) == 3, "a throttled copy should be waited out, not abandoned"
    assert waits == [1.0, 2.0], "the wait should back off rather than hammer Drive"


def test_a_refused_asset_copy_is_not_retried(tmp_path, monkeypatch):
    """A 400 is a real refusal. Asking again only delays reporting it."""
    path = tmp_path / "asset"
    path.write_bytes(b"data")
    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", lambda s: asyncio.sleep(0))
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(400, json={"error": "badRequest"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ToolkitError) as error:
                await Google("test-token", client).upload(
                    path, "asset", "image/png", "folder", retry=True
                )
            assert error.value.detail == "http_400", "the report should say which way it failed"

    asyncio.run(run())
    assert len(attempts) == 1


def test_the_document_upload_is_never_retried(tmp_path, monkeypatch):
    """A lost reply can still mean success: asking twice leaves two documents."""
    path = tmp_path / "doc.docx"
    path.write_bytes(b"data")
    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", lambda s: asyncio.sleep(0))
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(429, json={"error": "rateLimitExceeded"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ToolkitError):
                await Google("test-token", client).upload(
                    path, "doc", "application/octet-stream", "folder", convert=True
                )

    asyncio.run(run())
    assert len(attempts) == 1, "the document must never be uploaded twice"
