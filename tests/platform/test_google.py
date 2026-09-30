import asyncio
import io
import json
import zipfile

import httpx
import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.google import (
    LIBRARY,
    READ_ATTEMPTS,
    Google,
    asset_names,
    convert,
    google_text,
    save_report,
    verify,
)
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
            google = Google("test-token", client)
            report = await convert(root, manifest, google, original_name="School assembly")
            # Saved by the caller, as web.py does (#121).
            await save_report(root, report, google)
            return report

    report = asyncio.run(run())
    assert report["status"] == "completed_with_warnings"
    assert report["verification"] == "page_size_count_and_text_checked"
    # Only the sound and the film: the deck's picture imports into Slides on
    # its own, so a second copy of it beside the deck preserves nothing.
    assert [output["kind"] for output in report["assetOutputs"]] == ["audio", "video"]
    assert report["assetsNotCopied"] == 1
    assert uploads[0]["mimeType"] == "application/vnd.google-apps.presentation"
    assert uploads[0]["name"] == "School assembly – converted"
    # The saved copies reach Drive under the names, not the digests: this is the
    # point of naming them, and it is the upload call that has to carry it.
    saved = [upload["name"] for upload in uploads[1:-1]]
    assert saved and all(name.startswith("School assembly – ") for name in saved), saved
    assert saved == [output["name"] for output in report["assetOutputs"]]
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


def test_download_writes_the_file_and_returns_its_size(tmp_path):
    destination = tmp_path / "picked.docx"

    def handler(request):
        assert request.url.path == "/drive/v3/files/file123"
        assert request.url.params["alt"] == "media"
        return httpx.Response(200, content=b"a real docx body" * 100)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Google("private-token", client).download(
                "file123", destination, max_bytes=1_000_000
            )

    size = asyncio.run(run())
    assert size == len(b"a real docx body" * 100)
    assert destination.read_bytes() == b"a real docx body" * 100


def test_download_stops_at_the_size_limit(tmp_path):
    destination = tmp_path / "picked.docx"

    def handler(request):
        return httpx.Response(200, content=b"x" * 1000)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await Google("private-token", client).download("file123", destination, max_bytes=10)

    with pytest.raises(ToolkitError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.code == "upload_too_large"


def test_download_reports_an_unavailable_file(tmp_path):
    destination = tmp_path / "picked.docx"

    def handler(request):
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await Google("private-token", client).download("gone", destination, max_bytes=1000)

    with pytest.raises(ToolkitError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.code == "drive_file_unavailable"
    assert not destination.exists()


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


async def no_wait(_seconds):
    """Stands in for asyncio.sleep. Not a lambda calling asyncio.sleep(0):
    that name is the patched one, so it would call itself."""


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
        # The search again, after creating it: only ours is there.
        lambda r: httpx.Response(200, json={"files": [{"id": "library-new"}]}),
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


class Drive:
    """A stateful Drive stand-in for folders. Every call yields to the event
    loop first, the way a real network call does, so concurrent jobs
    interleave between the search and the create."""

    def __init__(self, elsewhere=None):
        self.folders = []  # (id, name, parent), oldest first
        self.calls = []
        # Another instance creating a library just as this one does.
        self.elsewhere = elsewhere

    async def handler(self, request):
        await asyncio.sleep(0)
        self.calls.append(request)
        if request.method == "GET":
            size = int(request.url.params["pageSize"])
            ids = [f[0] for f in self.folders if f[1] == LIBRARY and f[2] is None]
            return httpx.Response(200, json={"files": [{"id": i} for i in ids[:size]]})
        body = json_body(request)
        parent = (body.get("parents") or [None])[0]
        if parent is None and self.elsewhere:
            self.folders.append((self.elsewhere, LIBRARY, None))
            self.elsewhere = None
        folder_id = f"folder-{len(self.folders) + 1}"
        self.folders.append((folder_id, body["name"], parent))
        return httpx.Response(200, json={"id": folder_id})

    def libraries(self):
        return [f[0] for f in self.folders if f[1] == LIBRARY and f[2] is None]


def test_two_conversions_at_once_share_one_library_folder():
    """Issue #70: both jobs searched, both missed, and both created a library."""
    drive = Drive()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(drive.handler)) as client:
            one, two = Google("test-token", client), Google("test-token", client)
            jobs = await asyncio.gather(one.folder("First"), two.folder("Second"))
        return jobs, one.warnings + two.warnings

    jobs, warnings = asyncio.run(run())
    assert len(drive.libraries()) == 1, drive.folders
    parents = {f[2] for f in drive.folders if f[0] in jobs}
    assert parents == set(drive.libraries()), "both jobs belong in the one library"
    assert warnings == []


def test_a_library_made_elsewhere_at_the_same_moment_wins_and_is_reported():
    """The lock cannot reach another instance, so the re-check is what finds it."""
    drive = Drive(elsewhere="library-older")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(drive.handler)) as client:
            google = Google("test-token", client)
            job = await google.folder("Worksheet")
        return job, google.warnings

    job, warnings = asyncio.run(run())
    assert drive.libraries() == ["library-older", "folder-2"]
    assert next(f[2] for f in drive.folders if f[0] == job) == "library-older"
    assert [w["code"] for w in warnings] == ["library_duplicated"]
    assert all(c.method in {"GET", "POST"} for c in drive.calls), "nothing moved or deleted"


def test_a_failed_recheck_keeps_the_folder_it_made(monkeypatch):
    # The recheck is a read, so it is asked READ_ATTEMPTS times before it
    # counts as failed (#120).
    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", no_wait)
    responses = [
        lambda r: httpx.Response(200, json={"files": []}),
        lambda r: httpx.Response(200, json={"id": "library-new"}),
        *[lambda r: httpx.Response(500)] * READ_ATTEMPTS,
        lambda r: httpx.Response(200, json={"id": "job-1"}),
    ]

    async def run():
        calls, transport = transport_calls(responses)
        async with httpx.AsyncClient(transport=transport) as client:
            google = Google("test-token", client)
            await google.folder("Worksheet")
        return calls, google.warnings

    calls, warnings = asyncio.run(run())
    assert json_body(calls[-1])["parents"] == ["library-new"]
    assert warnings == []


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
    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", no_wait)
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
    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", no_wait)
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


def deck(*slides: list[str], assets: dict[str, str] | None = None) -> dict:
    """A manifest carrying only what asset naming reads: slides and assets."""
    return {
        "source": {"type": "pptx"},
        "pages": [
            {
                "index": index,
                # An id, or (id, the object's own name).
                "elements": [
                    {"assetIds": [i[0]], "name": i[1]}
                    if isinstance(i, tuple)
                    else {"assetIds": [i]}
                    for i in ids
                ],
            }
            for index, ids in enumerate(slides)
        ],
        "assets": {
            asset_id: {
                "id": asset_id,
                # The same rule both extractors use.
                "kind": mime.split("/", 1)[0]
                if mime.startswith(("image/", "audio/", "video/"))
                else "embedded",
                "mimeType": mime,
            }
            for asset_id, mime in (assets or {}).items()
        },
    }


def test_a_saved_picture_is_named_after_its_deck_and_slide():
    manifest = deck([], ["sha1"], assets={"sha1": "image/png"})
    assert asset_names(manifest, "Place Value") == {"sha1": "Place Value – slide 2 – image 1.png"}


def test_slide_numbers_are_padded_so_the_folder_sorts_in_deck_order():
    # Ten slides means two digits, or "slide 10" would sort before "slide 2".
    slides = [[] for _ in range(9)] + [["sha1"]]
    names = asset_names(deck(*slides, assets={"sha1": "image/png"}), "Assembly")
    assert names["sha1"] == "Assembly – slide 10 – image 1.png"
    one_digit = asset_names(deck([], ["sha1"], assets={"sha1": "image/png"}), "Assembly")
    assert one_digit["sha1"] == "Assembly – slide 2 – image 1.png"


def test_a_picture_reused_across_slides_names_every_slide_it_is_on():
    manifest = deck(["sha1"], ["sha1"], ["sha1"], assets={"sha1": "image/png"})
    assert asset_names(manifest, "Topic")["sha1"] == "Topic – slides 1, 2, 3 – image 1.png"


def test_a_logo_on_every_slide_is_summarised_rather_than_listed():
    manifest = deck(*[["sha1"] for _ in range(12)], assets={"sha1": "image/png"})
    assert asset_names(manifest, "Topic")["sha1"] == "Topic – slides 01 and 11 more – image 1.png"


def test_a_picture_no_slide_placed_is_not_given_a_slide_it_was_never_on():
    # An asset only a layout or a master uses. Naming it "slide 1" would be a lie.
    manifest = deck([], [], assets={"sha1": "image/png"})
    assert asset_names(manifest, "Topic")["sha1"] == "Topic – image 1.png"


def test_assets_are_numbered_in_deck_order_not_archive_order():
    manifest = deck(["late"], ["early"], assets={"early": "image/png", "late": "image/png"})
    names = asset_names(manifest, "Topic")
    assert names["late"] == "Topic – slide 1 – image 1.png"
    assert names["early"] == "Topic – slide 2 – image 2.png"


def test_each_kind_is_numbered_separately():
    manifest = deck(
        ["a"], ["b"], ["c"], assets={"a": "image/png", "b": "video/mp4", "c": "image/jpeg"}
    )
    names = asset_names(manifest, "Topic")
    assert names["a"].endswith("image 1.png")
    assert names["b"].endswith("video 1.mp4")
    assert names["c"].endswith("image 2.jpg")


def test_a_document_gets_no_slide_number_because_it_has_no_slides():
    # A .docx manifest has "pages", but they are section breaks rather than the
    # pages a reader counts, and nothing links an asset to one.
    manifest = {
        "source": {"type": "docx"},
        "pages": [{"index": 0, "elements": [{"assetIds": ["sha1"]}]}],
        "assets": {"sha1": {"id": "sha1", "kind": "image", "mimeType": "image/png"}},
    }
    assert asset_names(manifest, "Worksheet")["sha1"] == "Worksheet – image 1.png"


def test_a_name_that_could_break_a_download_is_made_safe():
    manifest = deck([], assets={"sha1": "image/png"})
    names = asset_names(manifest, 'Year 3/4: "maths"\tterm\n1')
    assert names["sha1"] == "Year 3 4 maths term1 – image 1.png"


def test_a_very_long_name_is_shortened_rather_than_refused():
    manifest = deck([], assets={"sha1": "image/png"})
    name = asset_names(manifest, "W" * 300)["sha1"]
    assert name == "W" * 80 + " – image 1.png"


def test_an_unknown_type_is_named_without_inventing_a_suffix():
    manifest = deck([], assets={"sha1": "application/x-not-a-real-type"})
    assert asset_names(manifest, "Topic")["sha1"] == "Topic – embedded 1"


def test_without_a_source_name_an_asset_is_still_named_usefully():
    manifest = deck([], ["sha1"], assets={"sha1": "image/png"})
    assert asset_names(manifest, "")["sha1"] == "slide 2 – image 1.png"


# --------------------------------------------- media keeps its own name


def test_media_is_named_after_the_file_the_teacher_inserted():
    # PowerPoint names an inserted video or sound after its file.
    manifest = deck([], [("v1", "Volcano eruption")], assets={"v1": "video/mp4"})
    assert asset_names(manifest, "Science")["v1"] == "Science – slide 2 – Volcano eruption.mp4"


def test_the_files_own_extension_is_not_doubled():
    manifest = deck([("a1", "Class song.m4a")], assets={"a1": "audio/mpeg"})
    assert asset_names(manifest, "Music")["a1"] == "Music – slide 1 – Class song.mp3"


def test_powerpoints_default_names_fall_back_to_the_number():
    manifest = deck(
        [("v1", "Video 2"), ("a1", "Recorded Sound"), ("p1", "Picture 3"), ("x1", "")],
        assets={"v1": "video/mp4", "a1": "audio/wav", "p1": "image/x-emf", "x1": "video/mp4"},
    )
    names = asset_names(manifest, "Topic")
    assert names["v1"] == "Topic – slide 1 – video 1.mp4"
    assert names["a1"] == "Topic – slide 1 – audio 1.wav"
    assert names["p1"] == "Topic – slide 1 – image 1.emf"
    assert names["x1"] == "Topic – slide 1 – video 2.mp4"


def test_two_files_with_one_name_stay_apart():
    manifest = deck(
        [("v1", "Intro")], [("v2", "Intro")], assets={"v1": "video/mp4", "v2": "video/mp4"}
    )
    names = asset_names(manifest, "Topic")
    assert names["v1"] == "Topic – slide 1 – Intro.mp4"
    assert names["v2"] == "Topic – slide 2 – Intro (2).mp4"


def test_an_unsafe_object_name_is_cleaned():
    manifest = deck([("v1", 'Week 3/4: "tides"')], assets={"v1": "video/mp4"})
    assert asset_names(manifest, "Topic")["v1"] == "Topic – slide 1 – Week 3 4 tides.mp4"


# ---------------------------------------------- #120: safe reads are retried


def read_through(responses, method="GET", monkeypatch=None):
    """Runs one Google.request against replayed replies; returns the result
    (or the error), the calls made, and the waits asked for."""
    waits: list[float] = []

    async def no_waiting(seconds):
        waits.append(seconds)

    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", no_waiting)

    async def run():
        calls, transport = transport_calls(responses)
        async with httpx.AsyncClient(transport=transport) as client:
            try:
                result = await Google("test-token", client).request(
                    method, "https://slides.googleapis.com/v1/presentations/p"
                )
            except ToolkitError as error:
                result = error
        return result, calls

    result, calls = asyncio.run(run())
    return result, calls, waits


def test_a_throttled_read_is_asked_again(monkeypatch):
    """One 503 on the verification read used to fail a conversion that worked."""
    result, calls, waits = read_through(
        [lambda r: httpx.Response(503), lambda r: httpx.Response(200, json={"slides": []})],
        monkeypatch=monkeypatch,
    )
    assert result == {"slides": []}
    assert len(calls) == 2
    assert len(waits) == 1 and 1.0 <= waits[0] <= 1.25, waits


def test_a_read_waits_as_long_as_google_asks(monkeypatch):
    result, _, waits = read_through(
        [
            lambda r: httpx.Response(429, headers={"Retry-After": "7"}),
            lambda r: httpx.Response(200, json={}),
        ],
        monkeypatch=monkeypatch,
    )
    assert result == {}
    assert waits == [7.0]


def test_a_dropped_connection_on_a_read_is_asked_again(monkeypatch):
    def dropped(request):
        raise httpx.ConnectError("reset", request=request)

    result, calls, _ = read_through(
        [dropped, lambda r: httpx.Response(200, json={"ok": True})], monkeypatch=monkeypatch
    )
    assert result == {"ok": True}
    assert len(calls) == 2


def test_a_read_that_keeps_failing_gives_up_after_its_attempts(monkeypatch):
    result, calls, waits = read_through([lambda r: httpx.Response(503)], monkeypatch=monkeypatch)
    assert isinstance(result, ToolkitError) and result.code == "google_failed"
    assert result.detail == "http_503"
    assert len(calls) == READ_ATTEMPTS
    assert len(waits) == READ_ATTEMPTS - 1
    assert waits[1] > waits[0], "each wait is longer than the last"


def test_a_read_refused_outright_is_not_asked_again(monkeypatch):
    result, calls, _ = read_through([lambda r: httpx.Response(404)], monkeypatch=monkeypatch)
    assert isinstance(result, ToolkitError)
    assert len(calls) == 1


def test_a_wait_longer_than_the_job_can_afford_is_not_waited_out(monkeypatch):
    result, calls, waits = read_through(
        [lambda r: httpx.Response(429, headers={"Retry-After": "3600"})], monkeypatch=monkeypatch
    )
    assert isinstance(result, ToolkitError)
    assert len(calls) == 1 and waits == []


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_a_request_that_changes_something_is_never_repeated(monkeypatch, method):
    """A lost or throttled reply to a create can still mean it was made."""
    result, calls, waits = read_through(
        [lambda r: httpx.Response(503), lambda r: httpx.Response(200, json={"id": "x"})],
        method=method,
        monkeypatch=monkeypatch,
    )
    assert isinstance(result, ToolkitError)
    assert len(calls) == 1 and waits == []


def test_the_library_search_survives_one_throttled_reply(monkeypatch):
    """The folder search is a read: throttled once, it is not a failed job,
    and no second library folder is made."""
    monkeypatch.setattr("workspace_toolkit.google.asyncio.sleep", no_wait)
    responses = [
        lambda r: httpx.Response(429),
        lambda r: httpx.Response(200, json={"files": [{"id": "library-1"}]}),
        lambda r: httpx.Response(200, json={"id": "job-1"}),
    ]

    async def run():
        calls, transport = transport_calls(responses)
        async with httpx.AsyncClient(transport=transport) as client:
            await Google("test-token", client).folder("Worksheet")
        return calls

    calls = asyncio.run(run())
    assert [c.method for c in calls] == ["GET", "GET", "POST"]
    assert json_body(calls[-1])["parents"] == ["library-1"]
