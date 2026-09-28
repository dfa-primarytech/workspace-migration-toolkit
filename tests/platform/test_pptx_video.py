"""Embedded video is taken out before a deck goes to Google (issue #36).

Google Slides does not import embedded video, and the conversion already
saves each video to Drive. Sending it anyway only costs upload time and counts
toward Google's 100 MB conversion limit. The slide keeps the video's poster
frame as an ordinary picture.
"""

from __future__ import annotations

import io
import re
import zipfile

from defusedxml import ElementTree
from workspace_toolkit.config import Settings
from workspace_toolkit.google import videos_removed_warnings
from workspace_toolkit.package import REL_NS, Package
from workspace_toolkit.pptx import NS, analyse, render_path

from .conftest import fixture_parts, write_pptx

P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
MEDIA = "http://schemas.microsoft.com/office/2007/relationships/media"
VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 400


def media_pic(shape_id, play_rid, media_rid, kind="video", poster="rId3"):
    element = "videoFile" if kind == "video" else "audioFile"
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="{kind} {shape_id}">'
        '<a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr>'
        '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        f'<p:nvPr><a:{element} r:link="{play_rid}"/><p:extLst>'
        '<p:ext uri="{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}">'
        f'<p14:media xmlns:p14="{P14}" r:embed="{media_rid}"/></p:ext></p:extLst></p:nvPr>'
        f'</p:nvPicPr><p:blipFill><a:blip r:embed="{poster}"/><a:stretch><a:fillRect/>'
        '</a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="1270000" cy="1270000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
        "</a:prstGeom></p:spPr></p:pic>"
    )


TIMING = (
    '<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">'
    '<p:childTnLst><p:video><p:cMediaNode vol="80000"><p:cTn id="2" fill="hold" display="0">'
    '<p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn><p:tgtEl>'
    '<p:spTgt spid="4"/></p:tgtEl></p:cMediaNode></p:video></p:childTnLst></p:cTn></p:par>'
    "</p:tnLst></p:timing>"
)


def without_video():
    """The shared fixture, minus the video it already carries on slide 2."""
    parts = fixture_parts()
    parts["ppt/slides/slide2.xml"] = parts["ppt/slides/slide2.xml"].replace(
        '<a:videoFile r:link="movie"/>', ""
    )
    parts["ppt/slides/_rels/slide2.xml.rels"] = re.sub(
        r'<Relationship Id="movie"[^>]*/>', "", parts["ppt/slides/_rels/slide2.xml.rels"]
    )
    del parts["ppt/media/video.mp4"]
    return parts


def video_deck(tmp_path, *, extra_rels="", name="video.pptx"):
    parts = without_video()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>",
        '<Override PartName="/ppt/media/media1.mp4" ContentType="video/mp4"/></Types>',
    )
    parts["ppt/slides/slide1.xml"] = (
        f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}"><p:cSld><p:spTree>'
        "<p:nvGrpSpPr/><p:grpSpPr/>"
        + media_pic(4, "rId2", "rId1")
        + media_pic(5, "rId5", "rId4", kind="audio")
        + f"</p:spTree></p:cSld>{TIMING}</p:sld>"
    )
    parts["ppt/slides/_rels/slide1.xml.rels"] = (
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="{MEDIA}" Target="../media/media1.mp4"/>'
        f'<Relationship Id="rId2" Type="{NS["r"]}/video" Target="../media/media1.mp4"/>'
        f'<Relationship Id="rId3" Type="{NS["r"]}/image" Target="../media/image.png"/>'
        f'<Relationship Id="rId4" Type="{MEDIA}" Target="../media/audio.wav"/>'
        f'<Relationship Id="rId5" Type="{NS["r"]}/audio" Target="../media/audio.wav"/>'
        f"{extra_rels}</Relationships>"
    )
    parts["ppt/media/media1.mp4"] = VIDEO_BYTES
    return write_pptx(tmp_path / name, parts)


def rendered(tmp_path, source):
    destination = tmp_path / "converted.pptx"
    report = render_path(source, destination, Settings())
    return report, zipfile.ZipFile(destination)


def test_the_video_goes_and_its_still_image_stays(tmp_path):
    report, out = rendered(tmp_path, video_deck(tmp_path))
    assert "ppt/media/media1.mp4" not in out.namelist()
    assert report["videosRemoved"] == [
        {
            "part": "ppt/media/media1.mp4",
            "bytes": len(VIDEO_BYTES),
            "usedBy": ["ppt/slides/slide1.xml"],
        }
    ]
    slide = ElementTree.fromstring(out.read("ppt/slides/slide1.xml"))
    pictures = slide.findall(".//p:pic", NS)
    assert len(pictures) == 2, "the poster frame must stay as a picture"
    assert pictures[0].find(".//a:blip", NS).get(f"{{{NS['r']}}}embed") == "rId3"
    assert pictures[0].find(".//a:videoFile", NS) is None
    assert slide.find(".//p:video", NS) is None, "nothing may try to play it"
    rels = out.read("ppt/slides/_rels/slide1.xml.rels").decode()
    assert "rId1" not in rels and "rId2" not in rels
    assert "/ppt/media/media1.mp4" not in out.read("[Content_Types].xml").decode()


def test_audio_is_left_alone(tmp_path):
    _, out = rendered(tmp_path, video_deck(tmp_path))
    assert "ppt/media/audio.wav" in out.namelist()
    slide = ElementTree.fromstring(out.read("ppt/slides/slide1.xml"))
    assert slide.find(".//a:audioFile", NS) is not None
    assert len(slide.findall(f".//{{{P14}}}media")) == 1, "the audio's p14:media stays"
    rels = out.read("ppt/slides/_rels/slide1.xml.rels").decode()
    assert "rId4" in rels and "rId5" in rels


def test_every_reference_in_the_result_still_resolves(tmp_path):
    # The invariant Google's importer relies on: no part names a relationship
    # that is gone, and no relationship names a part that is gone.
    _, out = rendered(tmp_path, video_deck(tmp_path))
    names = set(out.namelist())
    r = f"{{{NS['r']}}}"
    for rels_name in [n for n in names if n.endswith(".rels") and n != "_rels/.rels"]:
        folder, _, base = rels_name.rpartition("/")
        part = folder.removesuffix("_rels") + base.removesuffix(".rels")
        rels = ElementTree.fromstring(out.read(rels_name))
        ids = {rel.get("Id") for rel in rels}
        for rel in rels:
            if rel.get("TargetMode") != "External":
                target = (folder.removesuffix("_rels") + rel.get("Target")).replace(
                    "slides/../", ""
                )
                target = re.sub(r"[^/]+/\.\./", "", target)
                assert target in names, f"{rels_name} points at missing {target}"
        for node in ElementTree.fromstring(out.read(part)).iter():
            for key, value in node.attrib.items():
                if key.startswith(r) and value:
                    assert value in ids, f"{part} names missing {value}"


def test_a_video_file_also_used_as_a_picture_is_kept(tmp_path):
    # Odd, but possible: the same part referenced as an image elsewhere. It
    # cannot go without breaking that reference, so the video stays.
    extra = f'<Relationship Id="rId9" Type="{NS["r"]}/image" Target="../media/media1.mp4"/>'
    report, out = rendered(tmp_path, video_deck(tmp_path, extra_rels=extra))
    assert report["videosRemoved"] == []
    assert "ppt/media/media1.mp4" in out.namelist()


def test_a_part_that_cannot_be_confirmed_keeps_its_video(tmp_path, monkeypatch):
    monkeypatch.setattr("workspace_toolkit.pptx._strip_part", lambda data, rids: None)
    report, out = rendered(tmp_path, video_deck(tmp_path))
    assert report["videosRemoved"] == []
    assert "ppt/media/media1.mp4" in out.namelist()
    assert "rId2" in out.read("ppt/slides/_rels/slide1.xml.rels").decode()


def test_a_deck_without_video_is_written_as_before(tmp_path):
    source = write_pptx(tmp_path / "plain.pptx", without_video())
    report, out = rendered(tmp_path, source)
    assert report["videosRemoved"] == []
    assert set(out.namelist()) == set(zipfile.ZipFile(source).namelist())


def test_the_shared_fixtures_own_video_is_removed_too(tmp_path, pptx):
    # conftest's slide 2 carries a video with only a link relationship (no
    # p14:media) -- the older shape PowerPoint 2007 wrote.
    report, out = rendered(tmp_path, pptx)
    assert [v["part"] for v in report["videosRemoved"]] == ["ppt/media/video.mp4"]
    assert "ppt/media/video.mp4" not in out.namelist()
    assert b"videoFile" not in out.read("ppt/slides/slide2.xml")


def test_check_file_says_what_will_happen_to_a_video(tmp_path):
    manifest = analyse(video_deck(tmp_path), tmp_path / "out", Settings())
    notes = [w for w in manifest["warnings"] if w["code"] == "video_saved_separately"]
    assert len(notes) == 1
    assert "still image" in notes[0]["message"]


def _manifest_with_video():
    return {"assets": {"v": {"id": "v", "sourceParts": ["ppt/media/media1.mp4"]}}}


def test_the_report_says_where_the_video_went():
    videos = [{"part": "ppt/media/media1.mp4", "bytes": 42_000_000, "usedBy": []}]
    report = {"assetOutputs": [{"assetId": "v"}]}
    notes = videos_removed_warnings(videos, _manifest_with_video(), report)
    assert [n["code"] for n in notes] == ["videos_removed"]
    assert "42.0 MB" in notes[0]["message"]
    assert "in the conversion folder" in notes[0]["message"]


def test_a_video_whose_copy_failed_is_called_out():
    # Once taken out, the copy in Drive is the only one the conversion made.
    videos = [{"part": "ppt/media/media1.mp4", "bytes": 42_000_000, "usedBy": []}]
    notes = videos_removed_warnings(videos, _manifest_with_video(), {"assetOutputs": []})
    assert [n["code"] for n in notes] == ["videos_removed", "removed_video_not_saved"]
    assert "in the conversion folder" not in notes[0]["message"]
    assert "original file" in notes[1]["message"]


def test_the_stripped_deck_is_still_a_valid_package(tmp_path):
    _, out = rendered(tmp_path, video_deck(tmp_path))
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as copy:
        for name in out.namelist():
            copy.writestr(name, out.read(name))
    path = tmp_path / "again.pptx"
    path.write_bytes(data.getvalue())
    Package(path, Settings()).close()  # our own reader accepts it
    analyse(path, tmp_path / "again", Settings())
