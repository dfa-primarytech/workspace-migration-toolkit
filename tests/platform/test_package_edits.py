"""Package parts edited as bytes, then checked with the XML parser (#124, #136,
#137). A tag may carry any prefix and may be empty or paired: all are valid
OOXML, and each used to leave a package that no longer held together."""

from __future__ import annotations

import re
import zipfile

from defusedxml import ElementTree
from workspace_toolkit.config import Settings
from workspace_toolkit.package import (
    CONTENT_NS,
    REL_NS,
    Package,
    with_default,
    without_overrides,
    without_relationships,
)
from workspace_toolkit.pptx import NS

from .conftest import write_pptx
from .test_pictures import deck, encode, photo, pic, squeeze
from .test_pptx_video import rendered, video_deck

# ------------------------------------------------------------------ the helpers


def test_a_paired_relationship_is_removed_and_the_rest_kept():
    rels = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" Target="a"></Relationship>'
        '<Relationship Id="rId2" Target="b"/></Relationships>'
    )
    result = without_relationships(rels.encode(), {"rId1"})
    assert result is not None
    assert [r.get("Id") for r in ElementTree.fromstring(result)] == ["rId2"]


def test_a_relationship_split_over_lines_is_still_found():
    odd = f'<Relationships xmlns="{REL_NS}"><Relationship\nId="rId1"\nTarget="a"/></Relationships>'
    result = without_relationships(odd.encode(), {"rId1"})
    assert result is not None and b"rId1" not in result


def test_an_edit_that_cannot_be_read_back_is_refused():
    assert without_relationships(b"<Relationships", {"rId1"}) is None
    assert without_overrides(b"<Types", {"a.png"}) is None
    assert with_default(b"<Types/>", "jpeg", "image/jpeg") is None


def test_overrides_and_defaults_keep_the_documents_own_prefix():
    types = (
        f'<ct:Types xmlns:ct="{CONTENT_NS}"><ct:Default Extension="png" ContentType="image/png"/>'
        '<ct:Override PartName="/ppt/media/v.mp4" ContentType="video/mp4"></ct:Override>'
        "</ct:Types>"
    ).encode()
    kept = without_overrides(types, {"ppt/media/v.mp4"})
    assert kept is not None and b"v.mp4" not in kept
    added = with_default(kept, "jpeg", "image/jpeg")
    assert added is not None
    defaults = ElementTree.fromstring(added).findall(f"{{{CONTENT_NS}}}Default")
    assert {(d.get("Extension"), d.get("ContentType")) for d in defaults} == {
        ("png", "image/png"),
        ("jpeg", "image/jpeg"),
    }
    assert with_default(added, "JPEG", "image/jpeg") == added  # already declared


# ------------------------------------------------------------------ video removal


def repacked(path, edit):
    """The same package, with `edit(name, text)` applied to each XML part."""
    with zipfile.ZipFile(path) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    for name, data in parts.items():
        if name.endswith((".xml", ".rels")):
            parts[name] = edit(name, data.decode()).encode()
    return write_pptx(path, parts)


def test_a_paired_size_tag_survives_a_video_being_removed(tmp_path):
    source = repacked(
        video_deck(tmp_path),
        lambda name, text: re.sub(r'(<a:ext cx="\d+" cy="\d+")/>', r"\1></a:ext>", text),
    )
    report, out = rendered(tmp_path, source)
    assert [v["part"] for v in report["videosRemoved"]] == ["ppt/media/media1.mp4"]
    slide = ElementTree.fromstring(out.read("ppt/slides/slide1.xml"))
    sizes = slide.findall(".//a:xfrm/a:ext", NS)
    assert len(sizes) == 2 and all(s.get("cx") == "1270000" for s in sizes)


def test_paired_relationships_and_overrides_for_a_removed_video_go_too(tmp_path):
    def paired(name, text):
        if name.endswith(".rels"):
            return re.sub(r"(<Relationship [^>]*?)/>", r"\1></Relationship>", text)
        if name == "[Content_Types].xml":
            return re.sub(r"(<Override [^>]*?)/>", r"\1></Override>", text)
        return text

    report, out = rendered(tmp_path, repacked(video_deck(tmp_path), paired))
    assert [v["part"] for v in report["videosRemoved"]] == ["ppt/media/media1.mp4"]
    rels = ElementTree.fromstring(out.read("ppt/slides/_rels/slide1.xml.rels"))
    assert {r.get("Id") for r in rels} == {"rId3", "rId4", "rId5"}
    types = out.read("[Content_Types].xml").decode()
    assert "/ppt/media/media1.mp4" not in types
    # Every relationship left still resolves to a part in the package.
    with zipfile.ZipFile(tmp_path / "converted.pptx") as archive:
        names = set(archive.namelist())
    for rel in rels:
        assert "ppt/media/" + rel.get("Target").rsplit("/", 1)[-1] in names


# ------------------------------------------------------------------ picture compression


def photo_deck(tmp_path, prefix: bool, paired: bool):
    path = deck(
        tmp_path,
        {"photo.png": encode(photo(1200, 800), "PNG")},
        pic("rId1", 4, 8 / 3),
        overrides='<Override PartName="/ppt/media/photo.png" ContentType="image/png"/>',
    )

    def edit(name, text):
        if name == "[Content_Types].xml":
            # No JPEG declared yet, so compression has to add one.
            text = text.replace('<Default Extension="jpg" ContentType="image/jpeg"/>', "")
            if paired:
                text = re.sub(r"(<Override [^>]*?)/>", r"\1></Override>", text)
            if prefix:
                text = re.sub(r"<(/?)(Types|Default|Override)\b", r"<\1ct:\2", text)
                text = text.replace(f'xmlns="{CONTENT_NS}"', f'xmlns:ct="{CONTENT_NS}"')
        elif name.endswith(".rels") and paired:
            text = re.sub(r"(<Relationship [^>]*?)/>", r"\1></Relationship>", text)
        return text

    return repacked(path, edit)


def test_a_compressed_photo_has_a_content_type_whatever_the_prefix(tmp_path):
    for prefix, paired in ((False, False), (True, False), (True, True)):
        folder = tmp_path / f"{prefix}-{paired}"
        folder.mkdir()
        report, out = squeeze(photo_deck(folder, prefix, paired))
        [done] = report["picturesCompressed"]
        assert done["newPart"] == "ppt/media/photo.jpeg"
        package = Package(folder / "deck.pptx", Settings())
        try:
            assert package.mime("ppt/media/photo.jpeg") == "image/jpeg", (prefix, paired)
            assert "ppt/media/photo.png" not in package.overrides, (prefix, paired)
            (rel,) = package.relationships("ppt/slides/slide1.xml")
            assert rel["resolved"] == "ppt/media/photo.jpeg"
        finally:
            package.close()


def test_content_types_that_cannot_be_edited_leave_the_file_as_it_was(tmp_path, monkeypatch):
    path = photo_deck(tmp_path, prefix=False, paired=False)
    before = path.read_bytes()
    monkeypatch.setattr("workspace_toolkit.pictures.with_default", lambda *args: None)
    report, _ = squeeze(path)
    assert report["picturesCompressed"] == []
    assert report["skipped"]["content types not editable"] == 1
    assert path.read_bytes() == before
