"""Embedded video and sound, put back into the converted deck.

Google's import drops them. A video is saved to Drive beside the deck, so it is
put back with a Drive video element where its still picture was. The Slides API
cannot add a sound, so a sound is wrapped in a short video (its icon, with the
audio) and that is put there instead. Synthetic decks only.
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest
from workspace_toolkit import embedded_media as em
from workspace_toolkit.errors import ToolkitError

from .test_animation_video import BOX, deck, have_ffmpeg, pic, silent_wav

E = 12700  # EMU per point
P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"


def media_pic(spid, x, y, w, h, rid, trim=None, poster="rId2"):
    """A picture that plays an embedded clip, boxed in points."""
    t = f'<p14:trim st="{trim[0]}" end="{trim[1]}"/>' if trim else ""
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{spid}" name="clip {spid}"/><p:cNvPicPr/><p:nvPr><p:extLst>'
        f'<p:ext uri="x"><p14:media xmlns:p14="{P14}" r:embed="{rid}">{t}</p14:media></p:ext></p:extLst></p:nvPr>'
        f'</p:nvPicPr><p:blipFill><a:blip r:embed="{poster}"/></p:blipFill><p:spPr><a:xfrm>'
        f'<a:off x="{int(x * E)}" y="{int(y * E)}"/><a:ext cx="{int(w * E)}" cy="{int(h * E)}"/></a:xfrm>'
        "</p:spPr></p:pic>"
    )


RELS = (
    '<Relationship Id="rId3" Type="x/media" Target="../media/lesson.mp4"/>'
    '<Relationship Id="rId4" Type="x/media" Target="../media/bell.wav"/>'
)


def media_deck(tmp_path, shapes):
    return deck(
        tmp_path,
        shapes,
        "",
        media={"ppt/media/lesson.mp4": b"video", "ppt/media/bell.wav": silent_wav()},
        rels=RELS,
    )


VIDEO = media_pic(5, 100, 100, 400, 225, "rId3")
SOUND = media_pic(6, 50, 400, 40, 40, "rId4", trim=(200, 800))
HIDDEN = media_pic(7, -200, -200, 40, 40, "rId4")


def test_every_clip_that_shows_on_a_slide_is_found_with_its_place(tmp_path):
    clips = em.find_clips(media_deck(tmp_path, VIDEO + SOUND + HIDDEN + pic("9", *BOX)))

    assert [(c.slide, c.kind, c.part.rsplit("/", 1)[-1]) for c in clips] == [
        (1, "video", "lesson.mp4"),
        (1, "audio", "bell.wav"),
    ]
    assert clips[0].box == (100.0, 100.0, 400.0, 225.0)
    assert clips[1].trim == (200.0, 800.0)


def test_a_sound_hidden_off_the_slide_is_not_a_clip_to_place(tmp_path):
    clips = em.find_clips(media_deck(tmp_path, HIDDEN))

    assert clips == []


def test_a_saved_video_is_found_by_the_part_it_came_from():
    manifest = {
        "assets": {
            "sha1": {"id": "sha1", "sourceParts": ["ppt/media/lesson.mp4"]},
            "sha2": {"id": "sha2", "sourceParts": ["ppt/media/bell.wav"]},
        }
    }
    report = {
        "assetOutputs": [
            {"assetId": "sha1", "driveFileId": "drive1"},
            {"assetId": "sha2", "driveFileId": "drive2"},
        ]
    }

    assert em.saved_by_part(manifest, report) == {
        "ppt/media/lesson.mp4": "drive1",
        "ppt/media/bell.wav": "drive2",
    }
    assert em.saved_by_part(manifest, {}) == {}


class Drive:
    """Records what is sent, and answers with a presentation holding these pictures."""

    def __init__(self, stills, fail_batch=False, fail_upload=False):
        self.stills, self.batches, self.uploads = stills, [], []
        self.fail_batch, self.fail_upload = fail_batch, fail_upload

    async def inspect(self, presentation_id):
        return {
            "pageSize": {
                "width": {"magnitude": 1000 * E, "unit": "EMU"},
                "height": {"magnitude": 600 * E, "unit": "EMU"},
            },
            "slides": [
                {
                    "objectId": "s1",
                    "pageElements": [
                        {
                            "objectId": name,
                            "size": {
                                "width": {"magnitude": w * E, "unit": "EMU"},
                                "height": {"magnitude": h * E, "unit": "EMU"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": x * E,
                                "translateY": y * E,
                                "unit": "EMU",
                            },
                            "image": {},
                        }
                        for name, (x, y, w, h) in self.stills.items()
                    ],
                }
            ],
        }

    async def slides_batch(self, presentation_id, requests):
        self.batches.append(requests)
        if self.fail_batch:
            raise ToolkitError("google_failed", "refused", 502)
        return {}

    async def upload(self, path, name, mime, parent, **kwargs):
        if self.fail_upload:
            raise ToolkitError("upload_uncertain", "failed", 502)
        self.uploads.append((name, mime, parent, path.read_bytes()))
        return {"id": f"wrapped{len(self.uploads)}"}


STILLS = {"vstill": (100, 100, 400, 225), "astill": (50, 400, 40, 40), "logo": (800, 20, 60, 60)}


def run_videos(drive, path, saved, skip=()):
    return asyncio.run(em.place_videos(drive, "pres", path, saved, skip=skip))


def test_a_saved_video_goes_where_its_still_picture_was_and_the_still_goes(tmp_path):
    path = media_deck(tmp_path, VIDEO + SOUND)
    drive = Drive(STILLS)
    summary, notes = run_videos(drive, path, {"ppt/media/lesson.mp4": "drive1"})

    ((requests,),) = [drive.batches]
    video = requests[0]["createVideo"]
    assert video["source"] == "DRIVE"
    assert video["id"] == "drive1"
    properties = video["elementProperties"]
    assert properties["pageObjectId"] == "s1"
    assert properties["size"] == {
        "width": {"magnitude": 400.0, "unit": "PT"},
        "height": {"magnitude": 225.0, "unit": "PT"},
    }
    assert (properties["transform"]["translateX"], properties["transform"]["translateY"]) == (
        100.0,
        100.0,
    )
    assert requests[1] == {"deleteObject": {"objectId": "vstill"}}
    assert summary == {"placed": 1, "failed": 0}
    assert [n["code"] for n in notes] == ["embedded_video_placed"]


def test_a_sound_is_not_put_back_as_a_video_by_this_step(tmp_path):
    path = media_deck(tmp_path, SOUND)
    drive = Drive(STILLS)
    summary, _ = run_videos(drive, path, {"ppt/media/bell.wav": "drive2"})

    assert drive.batches == []
    assert summary == {"placed": 0, "failed": 0}


def test_a_video_with_no_saved_copy_is_reported_and_left_as_its_still(tmp_path):
    drive = Drive(STILLS)
    summary, notes = run_videos(drive, media_deck(tmp_path, VIDEO), {})

    assert drive.batches == []
    assert summary == {"placed": 0, "failed": 1}
    assert [n["code"] for n in notes] == ["embedded_video_not_placed"]


def test_a_slide_given_to_an_animation_video_is_left_alone(tmp_path):
    drive = Drive(STILLS)
    summary, _ = run_videos(
        drive, media_deck(tmp_path, VIDEO), {"ppt/media/lesson.mp4": "d"}, skip=(1,)
    )

    assert drive.batches == []
    assert summary == {"placed": 0, "failed": 0}


def test_a_refused_batch_leaves_the_still_and_never_stops_the_conversion(tmp_path):
    drive = Drive(STILLS, fail_batch=True)
    summary, notes = run_videos(drive, media_deck(tmp_path, VIDEO), {"ppt/media/lesson.mp4": "d"})

    assert summary == {"placed": 0, "failed": 1}
    assert [n["code"] for n in notes] == ["embedded_video_not_placed"]


def test_a_deck_with_no_embedded_video_sends_nothing_and_asks_google_nothing(tmp_path):
    class Silent:
        async def inspect(self, presentation_id):
            raise AssertionError("nothing to look at")

    summary, notes = asyncio.run(
        em.place_videos(Silent(), "pres", deck(tmp_path, pic("5", *BOX), ""), {})
    )

    assert (summary, notes) == ({"placed": 0, "failed": 0}, [])


# ---------------------------------------------------------------- sounds


def fake_wrap(deck_path, clip, out):
    out.write_bytes(b"wrapped " + clip.part.encode())


def run_sounds(drive, path, wrap=fake_wrap, skip=()):
    return asyncio.run(em.place_sounds(drive, "pres", "folder", path, skip=skip, wrap=wrap))


def test_a_sound_becomes_a_short_video_saved_in_the_folder_and_put_on_the_slide(tmp_path):
    drive = Drive(STILLS)
    summary, notes = run_sounds(drive, media_deck(tmp_path, VIDEO + SOUND))

    assert [u[:3] for u in drive.uploads] == [("Slide 1 sound - bell.mp4", "video/mp4", "folder")]
    ((requests,),) = [drive.batches]
    video = requests[0]["createVideo"]
    assert (video["source"], video["id"]) == ("DRIVE", "wrapped1")
    assert requests[1] == {"deleteObject": {"objectId": "astill"}}
    assert summary == {"placed": 1, "failed": 0}
    assert [n["code"] for n in notes] == ["sound_video_placed"]


def test_the_video_a_sound_is_wrapped_in_is_big_enough_to_use_and_stays_on_the_slide(tmp_path):
    drive = Drive(STILLS)
    run_sounds(drive, media_deck(tmp_path, SOUND))

    properties = drive.batches[0][0]["createVideo"]["elementProperties"]
    width = properties["size"]["width"]["magnitude"]
    height = properties["size"]["height"]["magnitude"]
    x, y = properties["transform"]["translateX"], properties["transform"]["translateY"]
    assert width >= 160 and height == pytest.approx(width * 9 / 16)
    assert x >= 0 and y >= 0 and x + width <= 1000 and y + height <= 600
    # The speaker icon sat at (50..90, 400..440); the video is centred on it.
    assert x + width / 2 == pytest.approx(70, abs=40) or x == 0


def test_a_sound_that_cannot_be_wrapped_is_reported_and_left_as_its_icon(tmp_path):
    def no_ffmpeg(deck_path, clip, out):
        raise RuntimeError("ffmpeg is needed")

    drive = Drive(STILLS)
    summary, notes = run_sounds(drive, media_deck(tmp_path, SOUND), wrap=no_ffmpeg)

    assert (drive.uploads, drive.batches) == ([], [])
    assert summary == {"placed": 0, "failed": 1}
    assert [n["code"] for n in notes] == ["sound_video_not_placed"]


def test_a_sound_video_that_cannot_be_put_on_the_slide_stays_saved_in_the_folder(tmp_path):
    drive = Drive(STILLS, fail_batch=True)
    summary, notes = run_sounds(drive, media_deck(tmp_path, SOUND))

    assert len(drive.uploads) == 1
    assert summary == {"placed": 0, "failed": 1}
    assert [n["code"] for n in notes] == ["sound_video_not_placed"]


def test_a_slide_given_to_an_animation_video_keeps_its_sounds_out_of_this_step(tmp_path):
    drive = Drive(STILLS)
    summary, _ = run_sounds(drive, media_deck(tmp_path, SOUND), skip=(1,))

    assert drive.uploads == []
    assert summary == {"placed": 0, "failed": 0}


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg is not installed")
def test_a_sound_is_wrapped_in_a_real_video_the_length_of_its_trim(tmp_path):
    path = media_deck(tmp_path, SOUND)
    (clip,) = em.find_clips(path)
    out = tmp_path / "wrapped.mp4"

    em.wrap_sound(path, clip, out)

    listing = subprocess.run(  # noqa: S603
        [em._ffmpeg(), "-hide_banner", "-i", str(out)], capture_output=True, text=True
    ).stderr
    streams = [x.strip() for x in listing.splitlines() if x.strip().startswith("Stream #")]
    assert [s.split(": ", 1)[1][:10] for s in streams] == ["Video: h26", "Audio: aac"]
    duration = [x for x in listing.splitlines() if "Duration" in x][0]
    assert "00:00:00.6" in duration or "00:00:00.5" in duration, duration  # trim 200..800 ms
