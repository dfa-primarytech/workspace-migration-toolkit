"""Online videos (YouTube and others) in a PowerPoint deck.

PowerPoint stores an online video as a picture whose video link is an external
address. Google's import keeps only the still picture, so the video was lost
without a word. A YouTube video is put back in place with the Slides API's
own video element; the other providers cannot play inside Slides, so their
still picture is given the link instead.
"""

from __future__ import annotations

import asyncio

import pytest
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.online_video import apply, classify
from workspace_toolkit.package import REL_NS
from workspace_toolkit.pptx import NS, analyse

from .conftest import write_pptx
from .test_pptx_video import P14, without_video

ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/embed/{ID}?feature=oembed",
        f"https://www.youtube.com/watch?v={ID}",
        f"https://youtu.be/{ID}",
        f"https://www.youtube-nocookie.com/embed/{ID}",
        f"https://m.youtube.com/watch?v={ID}&feature=share",
        f"https://www.youtube.com/shorts/{ID}",
        f"HTTP://YOUTU.BE/{ID}",
    ],
)
def test_every_common_youtube_address_gives_its_video_id(url):
    found = classify(url)

    assert found["provider"] == "youtube"
    assert found["videoId"] == ID


def test_a_start_time_is_kept_when_the_address_has_one():
    assert classify(f"https://youtu.be/{ID}?t=75")["start"] == 75
    assert classify(f"https://www.youtube.com/embed/{ID}?start=30")["start"] == 30
    assert classify(f"https://youtu.be/{ID}")["start"] is None


@pytest.mark.parametrize(
    ("url", "provider"),
    [
        ("https://vimeo.com/76979871", "vimeo"),
        ("https://player.vimeo.com/video/76979871", "vimeo"),
        ("https://www.slideshare.net/x/deck", "slideshare"),
        ("https://contoso.sharepoint.com/sites/a/video.mp4", "sharepoint"),
        ("https://contoso-my.sharepoint.com/:v:/g/personal/a/b", "sharepoint"),
        ("https://onedrive.live.com/?id=1", "onedrive"),
        ("https://example.org/video.mp4", "other"),
    ],
)
def test_other_providers_are_named_but_not_given_an_id(url, provider):
    found = classify(url)

    assert found["provider"] == provider
    assert found["videoId"] is None


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=" + "x" * 40,
        "https://evil.example/youtube.com/watch?v=" + ID,
        "javascript:alert(1)",
        "https://notyoutube.com/embed/" + ID,
    ],
)
def test_an_address_that_is_not_a_youtube_video_is_never_taken_for_one(url):
    assert classify(url)["videoId"] is None


# ---------------------------------------------------------------- reading a deck


def online_pic(url=f"https://www.youtube.com/embed/{ID}?feature=oembed", extra=""):
    return (
        '<p:pic><p:nvPicPr><p:cNvPr id="4" name="Online Media 3">'
        '<a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr>'
        '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        '<p:nvPr><a:videoFile r:link="rId2"/><p:extLst>'
        '<p:ext uri="{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}">'
        f'<p14:media xmlns:p14="{P14}" r:link="rId3"/></p:ext></p:extLst></p:nvPr>'
        '</p:nvPicPr><p:blipFill><a:blip r:embed="rId4"/><a:stretch><a:fillRect/>'
        '</a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="1270000" y="2540000"/>'
        '<a:ext cx="5080000" cy="3810000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
        f"</a:prstGeom></p:spPr></p:pic>{extra}"
    )


def online_deck(tmp_path, url=f"https://www.youtube.com/embed/{ID}?feature=oembed"):
    parts = without_video()
    parts["ppt/slides/slide1.xml"] = (
        f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}"><p:cSld><p:spTree>'
        "<p:nvGrpSpPr/><p:grpSpPr/>" + online_pic(url) + "</p:spTree></p:cSld></p:sld>"
    )
    parts["ppt/slides/_rels/slide1.xml.rels"] = (
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId2" Type="{NS["r"]}/video" Target="{url}" TargetMode="External"/>'
        f'<Relationship Id="rId3" Type="http://schemas.microsoft.com/office/2007/relationships/media"'
        f' Target="{url}" TargetMode="External"/>'
        f'<Relationship Id="rId4" Type="{NS["r"]}/image" Target="../media/image.png"/>'
        "</Relationships>"
    )
    return write_pptx(tmp_path / "online.pptx", parts)


def online_videos(manifest):
    return [e for page in manifest["pages"] for e in page["elements"] if "onlineVideo" in e]


def test_an_online_video_is_found_with_its_place_on_the_slide(tmp_path):
    manifest = analyse(online_deck(tmp_path), tmp_path / "out")

    (pic,) = online_videos(manifest)
    assert pic["onlineVideo"]["provider"] == "youtube"
    assert pic["onlineVideo"]["videoId"] == ID
    assert pic["bounds"] == {"x": 100.0, "y": 200.0, "width": 400.0, "height": 300.0}


def test_the_check_says_what_will_happen_to_an_online_video(tmp_path):
    manifest = analyse(online_deck(tmp_path), tmp_path / "out")

    (pic,) = online_videos(manifest)
    codes = [w["code"] for w in pic["warnings"]]
    assert "online_video" in codes
    note = next(w for w in pic["warnings"] if w["code"] == "online_video")
    assert "YouTube" in note["message"]
    assert ID not in str(note), "the report names the provider, never the address"


def test_a_picture_that_is_not_a_video_is_left_as_it_was(tmp_path):
    parts = without_video()
    manifest = analyse(write_pptx(tmp_path / "plain.pptx", parts), tmp_path / "out")

    assert not online_videos(manifest)


# ---------------------------------------------------------------- after the import


def manifest_with(*videos):
    elements = []
    for number, (url, bounds) in enumerate(videos):
        elements.append(
            {
                "id": f"slide_0_object_{number}",
                "type": "image",
                "bounds": bounds,
                "onlineVideo": {"url": url, **classify(url)},
                "warnings": [],
            }
        )
    return {"pages": [{"index": 0, "elements": elements}]}


def imported(*images):
    """A Slides presentation as the API describes it, with these pictures."""
    elements = []
    for name, (x, y, w, h) in images:
        elements.append(
            {
                "objectId": name,
                "size": {
                    "width": {"magnitude": w * 12700, "unit": "EMU"},
                    "height": {"magnitude": h * 12700, "unit": "EMU"},
                },
                "transform": {
                    "scaleX": 1,
                    "scaleY": 1,
                    "translateX": x * 12700,
                    "translateY": y * 12700,
                    "unit": "EMU",
                },
                "image": {},
            }
        )
    return {"slides": [{"objectId": "s1", "pageElements": elements}]}


class RecordingGoogle:
    def __init__(self, fail=False):
        self.batches = []
        self.fail = fail

    async def slides_batch(self, presentation_id, requests):
        self.batches.append((presentation_id, requests))
        if self.fail:
            raise ToolkitError("google_failed", "Google could not complete this operation.", 502)
        return {}


BOX = {"x": 100.0, "y": 200.0, "width": 400.0, "height": 300.0}
YOUTUBE = f"https://www.youtube.com/embed/{ID}"


def run_apply(google, presentation, manifest):
    return asyncio.run(apply(google, "deck", presentation, manifest))


def test_a_youtube_video_replaces_its_still_picture_in_the_same_place():
    google = RecordingGoogle()
    summary, notes = run_apply(
        google, imported(("poster", (100, 200, 400, 300))), manifest_with((YOUTUBE, BOX))
    )

    ((deck, requests),) = google.batches
    assert deck == "deck"
    video = requests[0]["createVideo"]
    assert video["source"] == "YOUTUBE"
    assert video["id"] == ID
    properties = video["elementProperties"]
    assert properties["pageObjectId"] == "s1"
    assert properties["size"] == {
        "width": {"magnitude": 400.0, "unit": "PT"},
        "height": {"magnitude": 300.0, "unit": "PT"},
    }
    assert properties["transform"]["translateX"] == 100.0
    assert properties["transform"]["translateY"] == 200.0
    assert properties["transform"]["unit"] == "PT"
    assert requests[1] == {"deleteObject": {"objectId": "poster"}}
    assert summary["embedded"] == 1
    assert [n["code"] for n in notes] == ["online_video_embedded"]


def test_the_picture_nearest_the_video_is_the_one_removed():
    google = RecordingGoogle()
    run_apply(
        google,
        imported(("logo", (10, 10, 50, 50)), ("poster", (101, 199, 399, 301))),
        manifest_with((YOUTUBE, BOX)),
    )

    deletes = [r["deleteObject"]["objectId"] for r in google.batches[0][1] if "deleteObject" in r]
    assert deletes == ["poster"], "a logo elsewhere on the slide must stay"


def test_a_video_with_no_matching_picture_is_added_and_nothing_is_deleted():
    google = RecordingGoogle()
    summary, _ = run_apply(
        google, imported(("logo", (10, 10, 50, 50))), manifest_with((YOUTUBE, BOX))
    )

    kinds = [next(iter(r)) for r in google.batches[0][1]]
    assert kinds == ["createVideo"]
    assert summary["embedded"] == 1


def test_a_start_time_is_set_on_the_video():
    google = RecordingGoogle()
    run_apply(
        google,
        imported(("poster", (100, 200, 400, 300))),
        manifest_with((YOUTUBE + "?start=30", BOX)),
    )

    update = next(r for r in google.batches[0][1] if "updateVideoProperties" in r)
    assert update["updateVideoProperties"]["videoProperties"]["start"] == 30
    assert update["updateVideoProperties"]["fields"] == "start"


def test_a_vimeo_video_cannot_play_so_its_picture_gets_the_link():
    google = RecordingGoogle()
    summary, notes = run_apply(
        google,
        imported(("poster", (100, 200, 400, 300))),
        manifest_with(("https://vimeo.com/76979871", BOX)),
    )

    (update,) = [r for r in google.batches[0][1] if "updateImageProperties" in r]
    body = update["updateImageProperties"]
    assert body["objectId"] == "poster"
    assert body["imageProperties"] == {"link": {"url": "https://vimeo.com/76979871"}}
    assert body["fields"] == "link"
    assert not [r for r in google.batches[0][1] if "createVideo" in r]
    assert summary["linked"] == 1
    assert [n["code"] for n in notes] == ["online_video_link_only"]


def test_a_refused_batch_is_reported_and_never_stops_the_conversion():
    google = RecordingGoogle(fail=True)
    summary, notes = run_apply(
        google, imported(("poster", (100, 200, 400, 300))), manifest_with((YOUTUBE, BOX))
    )

    assert summary["failed"] == 1
    assert summary["embedded"] == 0
    assert [n["code"] for n in notes] == ["online_video_not_added"]


def test_one_refused_video_does_not_lose_the_others():
    class FirstFails(RecordingGoogle):
        async def slides_batch(self, presentation_id, requests):
            await super().slides_batch(presentation_id, requests)
            if len(self.batches) == 1:
                raise ToolkitError("google_failed", "refused", 502)
            return {}

    google = FirstFails()
    other = (f"https://youtu.be/{ID[::-1]}", {"x": 10.0, "y": 10.0, "width": 80.0, "height": 60.0})
    summary, _ = run_apply(
        google,
        imported(("a", (100, 200, 400, 300)), ("b", (10, 10, 80, 60))),
        manifest_with((YOUTUBE, BOX), other),
    )

    assert len(google.batches) == 2
    assert (summary["embedded"], summary["failed"]) == (1, 1)


def test_a_deck_with_no_online_video_sends_nothing():
    google = RecordingGoogle()
    summary, notes = run_apply(google, imported(), {"pages": [{"index": 0, "elements": []}]})

    assert google.batches == []
    assert summary == {"embedded": 0, "linked": 0, "failed": 0}
    assert notes == []


def test_a_slide_the_import_dropped_is_reported_not_crashed_on():
    google = RecordingGoogle()
    manifest = manifest_with((YOUTUBE, BOX))
    manifest["pages"][0]["index"] = 5

    summary, notes = run_apply(google, imported(), manifest)

    assert google.batches == []
    assert summary["failed"] == 1
    assert [n["code"] for n in notes] == ["online_video_not_added"]
