"""Playing a slide's animation to a video (prototype).

Everything here uses small synthetic slides. The maths is checked on its own,
then a tiny deck is read, played at chosen moments, and the pixels are looked at.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import zipfile

import pytest
from defusedxml import ElementTree as ET
from PIL import Image
from workspace_toolkit import animation_video as av

PNS = (
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def png(colour, size=(10, 10)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


# ---------------------------------------------------------------- the maths


def test_easing_starts_at_zero_ends_at_one_and_never_goes_backwards():
    samples = [av.ease(i / 100, 0.5, 0.5) for i in range(101)]

    assert samples[0] == 0
    assert samples[-1] == pytest.approx(1)
    assert samples == sorted(samples)
    assert av.ease(0.5, 0.5, 0.5) == pytest.approx(0.5)
    assert av.ease(0.25, 0.5, 0.5) < 0.25, "it starts slowly"


def test_no_easing_is_a_straight_line_and_out_of_range_is_clamped():
    assert av.ease(0.3, 0, 0) == pytest.approx(0.3)
    assert av.ease(-1, 0.5, 0.5) == 0
    assert av.ease(2, 0.5, 0.5) == pytest.approx(1)


def test_a_path_is_followed_by_length_not_by_corner():
    path = [(0.0, 0.0), (0.1, 0.0), (0.1, 0.3)]  # 0.1 across, then 0.3 up: 0.4 long

    assert av.along(path, 0.0) == (0.0, 0.0)
    assert av.along(path, 0.25) == pytest.approx((0.1, 0.0))
    assert av.along(path, 0.625) == pytest.approx((0.1, 0.15))
    assert av.along(path, 1.0) == pytest.approx((0.1, 0.3))
    assert av.along([], 0.5) == (0.0, 0.0)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1+#ppt_w/2", 1.25),
        ("#ppt_x", 0.4),
        ("0-#ppt_h/2", -0.1),
        ("(#ppt_x+#ppt_y)*2", 1.0),
        ("-0.5", -0.5),
        ("1.5E-1", 0.15),
    ],
)
def test_an_animation_value_is_worked_out_from_the_shape_and_slide(text, value):
    variables = {"ppt_x": 0.4, "ppt_y": 0.1, "ppt_w": 0.5, "ppt_h": 0.2}

    assert av.evaluate(text, variables) == pytest.approx(value)


@pytest.mark.parametrize("text", ["__import__('os')", "1;2", "open('x')", "#ppt_x.real", "1 $ 2"])
def test_an_animation_value_is_never_run_as_code(text):
    with pytest.raises((ValueError, IndexError)):
        av.evaluate(text, {"ppt_x": 0.4})


# ---------------------------------------------------------------- the timeline


def set_visible(spid, delay, value="visible"):
    return (
        f'<p:set><p:cBhvr><p:cTn id="9" dur="1" fill="hold"><p:stCondLst><p:cond delay="{delay}"/>'
        f'</p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst>'
        f'<p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="{value}"/>'
        "</p:to></p:set>"
    )


def fade(spid, out=False, dur=500):
    return (
        f'<p:animEffect transition="{"out" if out else "in"}" filter="fade"><p:cBhvr><p:cTn id="9" dur="{dur}"/>'
        f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'
    )


def effect(klass, delay, behaviours, node="withEffect", extra=""):
    return (
        f'<p:par><p:cTn id="5" presetID="1" presetClass="{klass}" nodeType="{node}" fill="hold" {extra}>'
        f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>{behaviours}</p:childTnLst></p:cTn></p:par>'
    )


def click_group(*effects, after=0):
    return (
        '<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
        f'<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="{after}"/></p:stCondLst><p:childTnLst>'
        + "".join(effects)
        + "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>"
    )


def slide_xml(shapes: str, groups: str) -> str:
    return (
        f"<p:sld {PNS}><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>{shapes}</p:spTree></p:cSld>"
        '<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        f'<p:seq><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>{groups}</p:childTnLst></p:cTn>'
        "</p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing></p:sld>"
    )


def timeline_of(groups: str) -> av.Timeline:
    return av.parse_timeline(ET.fromstring(slide_xml("", groups)))


def test_effects_start_when_the_slide_says_nested_delays_add_up():
    groups = click_group(
        effect("entr", 2000, set_visible("5", 100) + fade("5")),
        after=1000,
    )
    timeline = timeline_of(groups)

    visible = next(e for e in timeline.effects if e.kind == "visibility")
    assert visible.start == 3100, "1000 for the group, 2000 for the effect, 100 for the step"
    assert timeline.entrance == {"5"}
    assert timeline.end_ms == 3500


def test_a_second_click_waits_for_the_first_to_finish():
    groups = click_group(
        effect("entr", 0, set_visible("5", 0) + fade("5", dur=1000))
    ) + click_group(effect("entr", 0, set_visible("6", 0)))
    timeline = timeline_of(groups)

    second = next(e for e in timeline.effects if e.shape == "6")
    assert second.start == 1000


def test_a_sound_cue_is_found_with_its_start_and_length():
    cue = (
        '<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="14460" fill="hold"/>'
        '<p:tgtEl><p:spTgt spid="11"/></p:tgtEl></p:cBhvr></p:cmd>'
    )
    timeline = timeline_of(click_group(effect("mediacall", 6500, cue)))

    assert [(c.shape, c.start, c.dur) for c in timeline.cues] == [("11", 6500, 14460)]
    assert timeline.end_ms == 6500 + 14460


def test_a_clip_s_volume_is_read_and_defaults_to_full():
    audio = (
        '<p:audio><p:cMediaNode vol="80000"><p:cTn id="7" display="0"/><p:tgtEl><p:spTgt spid="11"/>'
        "</p:tgtEl></p:cMediaNode></p:audio>"
    )
    timeline = timeline_of(click_group(effect("mediacall", 0, audio)))

    assert timeline.volumes == {"11": 0.8}


def test_a_slide_with_no_timing_has_nothing_to_play():
    timeline = av.parse_timeline(
        ET.fromstring(f"<p:sld {PNS}><p:cSld><p:spTree/></p:cSld></p:sld>")
    )

    assert (timeline.effects, timeline.cues, timeline.end_ms) == ([], [], 0)


# ---------------------------------------------------------------- a tiny deck


def pic(spid, x, y, w, h, media="rId2", extra=""):
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{spid}" name="Picture {spid}"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{media}"/></p:blipFill><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/>'
        f'<a:ext cx="{w}" cy="{h}"/></a:xfrm></p:spPr>{extra}</p:pic>'
    )


def deck(tmp_path, shapes, groups, media=None, rels=None):
    parts = {
        "ppt/presentation.xml": f'<p:presentation {PNS}><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
        '<p:sldSz cx="12700000" cy="7620000"/></p:presentation>',  # 1000 x 600 pt
        "ppt/_rels/presentation.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        'Target="slides/slide1.xml"/></Relationships>',
        "ppt/slides/slide1.xml": slide_xml(shapes, groups),
        "ppt/slides/_rels/slide1.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="../media/red.png"/>' + (rels or "") + "</Relationships>"
        ),
        "ppt/media/red.png": png((255, 0, 0)),
    }
    path = tmp_path / "deck.pptx"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in {**parts, **(media or {})}.items():
            archive.writestr(name, content)
    return path


def player_for(path, width=1000) -> av.Player:
    with zipfile.ZipFile(path) as archive:
        part = av.slide_part(archive, 1)
        root = ET.fromstring(archive.read(part))
        scene = av.read_scene(archive, part)
    return av.Player(scene, av.parse_timeline(root), width)


def colour_at(player: av.Player, ms: float, x: int, y: int):
    return player.frame(ms).convert("RGB").getpixel((x, y))


WHITE, RED = (255, 255, 255), (255, 0, 0)
BOX = (2540000, 2540000, 2540000, 2540000)  # 200 x 200 pt at 200,200


def test_a_picture_with_an_entrance_is_hidden_until_it_arrives(tmp_path):
    groups = click_group(effect("entr", 2000, set_visible("5", 0)))
    player = player_for(deck(tmp_path, pic("5", *BOX), groups))

    assert colour_at(player, 0, 300, 300) == WHITE
    assert colour_at(player, 1999, 300, 300) == WHITE
    assert colour_at(player, 2001, 300, 300) == RED


def test_a_picture_with_no_effect_is_always_there_and_one_that_exits_goes(tmp_path):
    groups = click_group(effect("exit", 1000, set_visible("5", 0, "hidden")))
    player = player_for(deck(tmp_path, pic("5", *BOX), groups))

    assert colour_at(player, 500, 300, 300) == RED
    assert colour_at(player, 1500, 300, 300) == WHITE


def test_a_fade_in_is_half_there_half_way(tmp_path):
    groups = click_group(effect("entr", 0, set_visible("5", 0) + fade("5", dur=1000)))
    player = player_for(deck(tmp_path, pic("5", *BOX), groups))

    r, g, b = colour_at(player, 500, 300, 300)
    assert r == 255
    assert 100 < g < 160, "about half way between red and white"
    assert colour_at(player, 1200, 300, 300) == RED


def test_a_motion_path_moves_the_picture_a_fraction_of_the_slide(tmp_path):
    motion = (
        '<p:animMotion origin="layout" path="M 0 0 L 0.3 0 " pathEditMode="relative"><p:cBhvr>'
        '<p:cTn id="8" dur="1000" fill="hold"/><p:tgtEl><p:spTgt spid="5"/></p:tgtEl></p:cBhvr></p:animMotion>'
    )
    groups = click_group(effect("path", 0, motion, extra='accel="0" decel="0"'))
    player = player_for(deck(tmp_path, pic("5", *BOX), groups))

    assert colour_at(player, 0, 300, 300) == RED
    assert colour_at(player, 0, 550, 300) == WHITE
    assert colour_at(player, 2000, 300, 300) == WHITE, "300 pt along: it has left its old place"
    assert colour_at(player, 2000, 550, 300) == RED, "and holds at the end of the path"


def test_a_grow_effect_makes_the_picture_bigger_about_its_centre(tmp_path):
    grow = (
        '<p:animScale><p:cBhvr><p:cTn id="8" dur="1000" fill="hold"/><p:tgtEl><p:spTgt spid="5"/></p:tgtEl></p:cBhvr>'
        '<p:by x="200000" y="200000"/></p:animScale>'
    )
    groups = click_group(effect("emph", 0, grow, extra='accel="0" decel="0"'))
    player = player_for(deck(tmp_path, pic("5", *BOX), groups))

    assert colour_at(player, 0, 150, 300) == WHITE
    assert colour_at(player, 2000, 150, 300) == RED, (
        "twice as wide: now reaches 100 pt further left"
    )


def test_a_fly_in_from_off_the_slide_ends_where_the_picture_sits(tmp_path):
    fly = set_visible("5", 0) + (
        '<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="8" dur="1000" fill="hold"/>'
        '<p:tgtEl><p:spTgt spid="5"/></p:tgtEl><p:attrNameLst><p:attrName>ppt_x</p:attrName></p:attrNameLst></p:cBhvr>'
        '<p:tavLst><p:tav tm="0"><p:val><p:strVal val="1+#ppt_w/2"/></p:val></p:tav>'
        '<p:tav tm="100000"><p:val><p:strVal val="#ppt_x"/></p:val></p:tav></p:tavLst></p:anim>'
    )
    groups = click_group(effect("entr", 0, fly, extra='accel="0" decel="0"'))
    player = player_for(deck(tmp_path, pic("5", *BOX), groups))

    assert colour_at(player, 1, 300, 300) == WHITE, "it starts off the right edge"
    assert colour_at(player, 2000, 300, 300) == RED, "and lands on its own place"


def test_transparency_lasts_only_as_long_as_it_says(tmp_path):
    faint = (
        '<p:set><p:cBhvr><p:cTn id="8" dur="1000"/><p:tgtEl><p:spTgt spid="5"/></p:tgtEl><p:attrNameLst>'
        '<p:attrName>style.opacity</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="0.5"/></p:to></p:set>'
    )
    groups = click_group(effect("emph", 0, faint).replace('fill="hold"', ""))
    player = player_for(deck(tmp_path, pic("5", *BOX), groups))

    assert colour_at(player, 500, 300, 300) != RED
    assert colour_at(player, 1500, 300, 300) == RED


def test_a_picture_in_a_group_lands_where_the_group_puts_it(tmp_path):
    inner = pic("6", 0, 0, 1270000, 1270000)  # 100 pt square, in the group's own space
    group = (
        '<p:grpSp><p:nvGrpSpPr><p:cNvPr id="5" name="Group"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>'
        '<a:xfrm><a:off x="5080000" y="2540000"/><a:ext cx="2540000" cy="2540000"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="1270000" cy="1270000"/></a:xfrm></p:grpSpPr>'
        + inner
        + "</p:grpSp>"
    )
    player = player_for(deck(tmp_path, group, ""))

    # The group is 200 pt square at (400, 200) and shows its 100 pt child at twice the size.
    assert colour_at(player, 0, 500, 300) == RED
    assert colour_at(player, 0, 700, 300) == WHITE


def test_a_picture_can_be_cropped(tmp_path):
    cropped = (
        pic("5", *BOX)
        .replace("<a:blip r:embed", "<a:blip r:embed")
        .replace("</p:blipFill>", '<a:srcRect l="50000"/></p:blipFill>')
    )
    two_tone = Image.new("RGB", (20, 10), (0, 0, 255))
    two_tone.paste((255, 0, 0), (10, 0, 20, 10))
    buffer = io.BytesIO()
    two_tone.save(buffer, "PNG")
    player = player_for(deck(tmp_path, cropped, "", media={"ppt/media/red.png": buffer.getvalue()}))

    assert colour_at(player, 0, 300, 300) == RED, "the left half, which is blue, is cropped away"


def test_a_slide_that_does_not_exist_is_refused_clearly(tmp_path):
    with zipfile.ZipFile(deck(tmp_path, pic("5", *BOX), "")) as archive:
        with pytest.raises(ValueError, match="no slide 9"):
            av.slide_part(archive, 9)


def test_an_unreadable_picture_is_skipped_not_fatal(tmp_path):
    player = player_for(
        deck(tmp_path, pic("5", *BOX), "", media={"ppt/media/red.png": b"not a picture"})
    )

    assert colour_at(player, 0, 300, 300) == WHITE


# ---------------------------------------------------------------- sound and video


def test_a_cue_plays_its_picture_s_sound_from_its_trim_at_its_time(tmp_path):
    sound = (
        '<p:pic><p:nvPicPr><p:cNvPr id="11" name="clip"/><p:cNvPicPr/><p:nvPr><p:extLst><p:ext uri="x">'
        '<p14:media xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" r:embed="rId3">'
        '<p14:trim st="4000" end="9000"/></p14:media></p:ext></p:extLst></p:nvPr></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="rId2"/></p:blipFill><p:spPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="100" cy="100"/></a:xfrm></p:spPr></p:pic>'
    )
    cue = (
        '<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="3000" fill="hold"/>'
        '<p:tgtEl><p:spTgt spid="11"/></p:tgtEl></p:cBhvr></p:cmd>'
        '<p:audio><p:cMediaNode vol="56000"><p:cTn id="7" display="0"/><p:tgtEl><p:spTgt spid="11"/>'
        "</p:tgtEl></p:cMediaNode></p:audio>"
    )
    path = deck(
        tmp_path,
        sound,
        click_group(effect("mediacall", 2500, cue)),
        media={"ppt/media/media1.wav": b"RIFF"},
        rels='<Relationship Id="rId3" Type="x/media" Target="../media/media1.wav"/>',
    )
    with zipfile.ZipFile(path) as archive:
        part = av.slide_part(archive, 1)
        scene = av.read_scene(archive, part)
        timeline = av.parse_timeline(ET.fromstring(archive.read(part)))

    found = av._audio_inputs(scene, timeline, tmp_path, 60)

    assert [(delay, trim, volume) for _, delay, trim, volume in found] == [
        (2500, (4000, 3000), 0.56)
    ]


def have_ffmpeg() -> bool:
    try:
        return bool(
            av._ffmpeg()
            and (shutil.which(av._ffmpeg()) or av._ffmpeg().endswith(".exe") or "/" in av._ffmpeg())
        )
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg is not installed")
def test_a_slide_plays_to_an_mp4_the_length_of_its_animation(tmp_path):
    groups = click_group(effect("entr", 0, set_visible("5", 0) + fade("5", dur=1000)))
    path = deck(tmp_path, pic("5", *BOX), groups)
    out = tmp_path / "out.mp4"

    summary = av.render_video(path, 1, out, fps=10, width=320)

    assert out.exists() and out.stat().st_size > 1000
    assert summary["seconds"] == pytest.approx(1.5)
    assert summary["frames"] == 15
    assert summary["framesDrawn"] < summary["frames"], (
        "a still moment is drawn once, not every frame"
    )
    assert out.read_bytes()[4:8] == b"ftyp"
    # Only picture (and sound): an extra empty text track kept Drive from
    # processing a video, so it never played.
    listing = subprocess.run(  # noqa: S603
        [av._ffmpeg(), "-hide_banner", "-i", str(out)], capture_output=True, text=True
    ).stderr
    streams = [line for line in listing.splitlines() if line.strip().startswith("Stream #")]
    assert len(streams) == 1 and "Video: h264" in streams[0], streams


def test_a_slide_with_no_animation_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no animation"):
        av.render_video(deck(tmp_path, pic("5", *BOX), ""), 1, tmp_path / "x.mp4")


# ---------------------------------------------------------------- putting it on the slide


class Drive:
    """Records what is sent to Drive and Slides."""

    def __init__(self, fail_upload=False, fail_batch=False, slides=1):
        self.uploads, self.batches = [], []
        self.fail_upload, self.fail_batch = fail_upload, fail_batch
        self.slides = slides

    async def upload(self, path, name, mime, parent, **kwargs):
        if self.fail_upload:
            raise ToolkitError("upload_uncertain", "A Google upload failed.", 502)
        self.uploads.append((name, mime, parent, path.read_bytes()))
        return {"id": f"video{len(self.uploads)}"}

    async def inspect(self, presentation_id):
        return {
            "pageSize": {
                "width": {"magnitude": 12700000, "unit": "EMU"},
                "height": {"magnitude": 7620000, "unit": "EMU"},
            },
            "slides": [
                {
                    "objectId": f"s{i}",
                    "pageElements": [{"objectId": f"a{i}"}, {"objectId": f"b{i}"}],
                }
                for i in range(1, self.slides + 1)
            ],
        }

    async def slides_batch(self, presentation_id, requests):
        self.batches.append((presentation_id, requests))
        if self.fail_batch:
            raise ToolkitError("google_failed", "refused", 502)
        return {}


def fake_render(deck, number, out, **kwargs):
    out.write_bytes(b"mp4 of slide %d" % number)
    return {"seconds": 5.0, "notes": []}


def run_attach(drive, slides, render=fake_render, deck="deck.pptx"):
    return asyncio.run(av.attach(drive, "pres", "folder", deck, slides, render=render))


from workspace_toolkit.errors import ToolkitError  # noqa: E402


def test_the_video_is_saved_in_the_conversion_folder_and_put_on_the_slide():
    drive = Drive()
    summary, notes = run_attach(drive, [1])

    assert drive.uploads == [("Slide 1 animation.mp4", "video/mp4", "folder", b"mp4 of slide 1")]
    ((deck, requests),) = drive.batches
    assert deck == "pres"
    video = requests[0]["createVideo"]
    assert video["source"] == "DRIVE"
    assert video["id"] == "video1"
    properties = video["elementProperties"]
    assert properties["pageObjectId"] == "s1"
    assert properties["size"] == {
        "width": {"magnitude": 1000.0, "unit": "PT"},
        "height": {"magnitude": 600.0, "unit": "PT"},
    }
    assert (properties["transform"]["translateX"], properties["transform"]["translateY"]) == (0, 0)
    assert summary == {"saved": 1, "placed": 1, "failed": 0}
    assert [n["code"] for n in notes] == ["animation_video_placed"]


def test_the_pictures_the_video_replaces_are_removed_after_it_is_made():
    drive = Drive()
    run_attach(drive, [1])

    kinds = [next(iter(r)) for r in drive.batches[0][1]]
    assert kinds == ["createVideo", "deleteObject", "deleteObject"]
    assert [r["deleteObject"]["objectId"] for r in drive.batches[0][1][1:]] == ["a1", "b1"]


def test_each_slide_gets_its_own_video_and_its_own_batch():
    drive = Drive(slides=3)
    summary, _ = run_attach(drive, [1, 3])

    assert [u[0] for u in drive.uploads] == ["Slide 1 animation.mp4", "Slide 3 animation.mp4"]
    assert [b[1][0]["createVideo"]["elementProperties"]["pageObjectId"] for b in drive.batches] == [
        "s1",
        "s3",
    ]
    assert summary["placed"] == 2


def test_a_video_that_cannot_be_put_on_the_slide_is_kept_in_the_folder_and_the_slide_left_alone():
    drive = Drive(fail_batch=True)
    summary, notes = run_attach(drive, [1])

    assert len(drive.uploads) == 1
    assert summary == {"saved": 1, "placed": 0, "failed": 1}
    assert [n["code"] for n in notes] == ["animation_video_saved_only"]


def test_a_slide_that_cannot_be_played_is_reported_and_nothing_is_sent():
    def broken(deck, number, out, **kwargs):
        raise ValueError("This slide has no animation to play.")

    drive = Drive()
    summary, notes = run_attach(drive, [1], render=broken)

    assert (drive.uploads, drive.batches) == ([], [])
    assert summary == {"saved": 0, "placed": 0, "failed": 1}
    assert [n["code"] for n in notes] == ["animation_video_failed"]


def test_a_failed_upload_stops_that_slide_but_not_the_run():
    drive = Drive(fail_upload=True)
    summary, notes = run_attach(drive, [1])

    assert drive.batches == []
    assert summary["failed"] == 1
    assert [n["code"] for n in notes] == ["animation_video_failed"]


def test_a_slide_number_the_presentation_does_not_have_is_reported():
    drive = Drive(slides=1)
    summary, notes = run_attach(drive, [7])

    assert drive.batches == []
    assert summary["failed"] == 1


def test_only_slides_with_real_animation_are_picked_automatically(tmp_path):
    busy = click_group(*[effect("entr", i * 100, set_visible("5", 0)) for i in range(25)])
    assert av.select_slides(deck(tmp_path, pic("5", *BOX), busy)) == [1]

    quiet = click_group(effect("entr", 0, set_visible("5", 0)))
    assert av.select_slides(deck(tmp_path, pic("5", *BOX), quiet)) == []
    assert av.select_slides(deck(tmp_path, pic("5", *BOX), ""), min_effects=1) == []


# ---------------------------------------------------------------- recordings staff made


def test_a_recording_staff_made_is_used_and_the_slide_is_not_played(tmp_path):
    made = tmp_path / "Lesson 2 - slide 1.mp4"
    made.write_bytes(b"recorded in PowerPoint")
    played = []

    def render(deck, number, out, **kwargs):
        played.append(number)

    drive = Drive()
    summary, notes = asyncio.run(
        av.attach(drive, "pres", "folder", "deck.pptx", [1], render=render, recordings={1: made})
    )

    assert played == [], "their recording is used as it is"
    assert drive.uploads == [
        ("Slide 1 animation.mp4", "video/mp4", "folder", b"recorded in PowerPoint")
    ]
    assert drive.batches[0][1][0]["createVideo"]["source"] == "DRIVE"
    assert summary == {"saved": 1, "placed": 1, "failed": 0}
    assert [n["code"] for n in notes] == ["animation_video_placed"]


def test_a_slide_with_no_recording_is_still_played_when_asked_for():
    drive = Drive(slides=2)
    played = []

    def render(deck, number, out, **kwargs):
        played.append(number)
        out.write_bytes(b"mp4")

    asyncio.run(
        av.attach(drive, "pres", "folder", "deck.pptx", [1, 2], render=render, recordings={})
    )

    assert played == [1, 2]


@pytest.mark.parametrize(
    "name",
    [
        "Lesson 2 - slide 6.mp4",
        "lesson 2 - Slide 6.MP4",
        "Lesson 2 – slide 6.mp4",
        "Lesson 2 - slide  6.mp4",
    ],
)
def test_a_recording_is_found_by_the_deck_name_and_slide_number(name):
    assert av.match_recordings("Lesson 2.pptx", [name, "notes.txt"]) == {6: name}


def test_only_this_decks_recordings_are_taken():
    names = [
        "Lesson 2 - slide 6.mp4",
        "Lesson 20 - slide 6.mp4",
        "Another deck - slide 6.mp4",
        "Lesson 2 - slide 6.mov",
        "Lesson 2 - slide six.mp4",
        "Lesson 2 - slide 6.mp4.txt",
        "Lesson 2 - slide 0.mp4",
        "Lesson 2 - slide 9.mp4",
    ]

    assert av.match_recordings("Lesson 2.pptx", names) == {
        6: "Lesson 2 - slide 6.mp4",
        9: "Lesson 2 - slide 9.mp4",
    }


def test_a_deck_name_with_punctuation_is_matched_literally():
    assert av.match_recordings("Year 7 (Maps) [v2].pptx", ["Year 7 (Maps) [v2] - slide 3.mp4"]) == {
        3: "Year 7 (Maps) [v2] - slide 3.mp4"
    }
    assert av.match_recordings("A.pptx", ["AB - slide 1.mp4", "A. - slide 1.mp4"]) == {}


def test_the_select_command_lists_the_slides_worth_recording(tmp_path, capsys):
    busy = click_group(*[effect("entr", i * 100, set_visible("5", 0)) for i in range(25)])
    path = deck(tmp_path, pic("5", *BOX), busy)

    av.main(["select", str(path)])

    assert capsys.readouterr().out.strip() == "[1]"


# ---------------------------------------------------------------- the check report


def checked(tmp_path, groups):
    from workspace_toolkit.pptx import analyse

    from .conftest import fixture_parts, write_pptx

    parts = fixture_parts()
    parts["ppt/slides/slide1.xml"] = slide_xml(pic("5", *BOX), groups)
    parts["ppt/slides/_rels/slide1.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="../media/image.png"/></Relationships>'
    )
    manifest = analyse(write_pptx(tmp_path / "check.pptx", parts), tmp_path / "out")
    return [w for w in manifest["warnings"] if w.get("slideIndex") == 1]


def test_the_check_calls_out_a_slide_that_is_a_timed_scene(tmp_path):
    busy = click_group(*[effect("entr", i * 100, set_visible("5", 0)) for i in range(25)])
    found = {w["code"]: w for w in checked(tmp_path, busy)}

    assert "heavy_animation" in found
    assert found["heavy_animation"]["effects"] == 25
    assert "video" in found["heavy_animation"]["message"].lower()


def test_the_check_leaves_an_ordinary_click_to_reveal_slide_to_the_general_note(tmp_path):
    quiet = click_group(effect("entr", 0, set_visible("5", 0) + fade("5")))
    codes = [w["code"] for w in checked(tmp_path, quiet)]

    assert "heavy_animation" not in codes
    assert "timing" in codes


def test_a_failed_recording_says_why_in_the_log_but_not_in_the_report(caplog):
    def broken(deck, number, out, **kwargs):
        raise RuntimeError("ffmpeg could not make the video: Out of memory")

    with caplog.at_level("WARNING"):
        _, notes = run_attach(Drive(), [1], render=broken)

    assert "Out of memory" in caplog.text
    assert "Out of memory" not in str(notes), "the report never carries ffmpeg's own words"


def test_a_failed_upload_says_why_in_the_log(caplog):
    with caplog.at_level("WARNING"):
        run_attach(Drive(fail_upload=True), [1])

    assert "animation_video_failed" in caplog.text
    assert "upload_uncertain" in caplog.text


def silent_wav(seconds=1, rate=8000) -> bytes:
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(2) * rate * seconds)
    return out.getvalue()


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg is not installed")
def test_a_video_with_sound_holds_only_picture_and_sound(tmp_path):
    sound = (
        '<p:pic><p:nvPicPr><p:cNvPr id="11" name="clip"/><p:cNvPicPr/><p:nvPr><p:extLst><p:ext uri="x">'
        '<p14:media xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" r:embed="rId3"/>'
        '</p:ext></p:extLst></p:nvPr></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/></p:blipFill><p:spPr>'
        '<a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm></p:spPr></p:pic>'
    )
    cue = (
        '<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="1000" fill="hold"/>'
        '<p:tgtEl><p:spTgt spid="11"/></p:tgtEl></p:cBhvr></p:cmd>'
    )
    groups = click_group(
        effect("entr", 0, set_visible("5", 0) + fade("5", dur=500)), effect("mediacall", 0, cue)
    )
    path = deck(
        tmp_path,
        pic("5", *BOX) + sound,
        groups,
        media={"ppt/media/media1.wav": silent_wav()},
        rels='<Relationship Id="rId3" Type="x/media" Target="../media/media1.wav"/>',
    )
    out = tmp_path / "out.mp4"

    summary = av.render_video(path, 1, out, fps=10, width=320)

    listing = subprocess.run(  # noqa: S603
        [av._ffmpeg(), "-hide_banner", "-i", str(out)], capture_output=True, text=True
    ).stderr
    streams = [
        line.split(":", 2)[2].strip()[:12]
        for line in listing.splitlines()
        if line.strip().startswith("Stream #")
    ]
    assert summary["soundCues"] == 1
    assert [x[:11] for x in streams] == ["Video: h264", "Audio: aac "], streams
