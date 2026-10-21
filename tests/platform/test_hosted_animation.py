"""The hosted conversion records animations and sounds, and nothing there can stop it."""

import asyncio

import httpx
from workspace_toolkit import animation_video, embedded_media
from workspace_toolkit.google import Google, convert
from workspace_toolkit.package import PPTX_MIME
from workspace_toolkit.pptx import analyse


def run_convert(pptx, tmp_path, monkeypatch, record, sounds, enabled=True):
    root = tmp_path / "job"
    root.mkdir()
    (root / "source.pptx").write_bytes(pptx.read_bytes())
    manifest = analyse(root / "source.pptx", root / "result")
    monkeypatch.setenv("WMT_HOSTED_ANIMATION", "on" if enabled else "off")
    monkeypatch.setattr(animation_video, "hosted_enabled", lambda: enabled)
    monkeypatch.setattr(animation_video, "record_hosted", record)
    monkeypatch.setattr(embedded_media, "place_sounds", sounds)
    monkeypatch.setattr(animation_video, "select_slides", lambda deck: [2])

    def handler(request):
        if request.url.path.endswith("/about"):
            return httpx.Response(
                200,
                json={"importFormats": {PPTX_MIME: ["application/vnd.google-apps.presentation"]}},
            )
        if request.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"id": "folder1"})
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/u"})
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "up1"})
        if request.url.host == "slides.googleapis.com":
            return httpx.Response(200, json={"pageSize": {}, "slides": [], "presentationId": "up1"})
        raise AssertionError(str(request.url))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await convert(root, manifest, Google("t", client), original_name="Deck")

    return asyncio.run(go())


def test_the_hosted_conversion_records_and_reports(pptx, tmp_path, monkeypatch):
    seen = {}

    async def record(google, presentation_id, folder_id, deck, **kw):
        seen["folder"] = folder_id
        return {"saved": 1, "placed": 1, "failed": 0}, [{"code": "note_a"}]

    async def sounds(google, presentation_id, folder_id, deck, *, skip=(), **kw):
        seen["skip"] = skip
        return {"placed": 2, "failed": 0}, [{"code": "note_b"}]

    report = run_convert(pptx, tmp_path, monkeypatch, record, sounds)

    assert report["animationVideos"] == {"saved": 1, "placed": 1, "failed": 0}
    assert report["soundVideos"] == {"placed": 2, "failed": 0}
    assert seen == {"folder": "folder1", "skip": (2,)}, "a recorded slide's sounds are its video's"
    codes = [w["code"] for w in report["warnings"]]
    assert "note_a" in codes and "note_b" in codes


def test_a_failing_sound_step_never_stops_the_conversion(pptx, tmp_path, monkeypatch):
    async def record(*a, **k):
        return {"saved": 0, "placed": 0, "failed": 0}, []

    async def sounds(*a, **k):
        raise RuntimeError("ffmpeg fell over")

    report = run_convert(pptx, tmp_path, monkeypatch, record, sounds)

    assert report["status"] == "completed_with_warnings"
    assert "soundVideos" not in report


def test_nothing_runs_where_recording_is_off(pptx, tmp_path, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("should not run")

    report = run_convert(pptx, tmp_path, monkeypatch, boom, boom, enabled=False)

    assert report["status"] == "completed_with_warnings"
    assert "animationVideos" not in report
