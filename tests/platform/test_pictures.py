"""Opt-in picture compression before a file goes to Google (issue #36, step 3)."""

from __future__ import annotations

import io
import os
import struct
import zipfile
import zlib

import pytest
from defusedxml import ElementTree
from PIL import Image, ImageDraw
from workspace_toolkit.config import Settings
from workspace_toolkit.package import DOCX, PPTX, REL_NS, Package
from workspace_toolkit.pictures import MIN_BYTES, compress
from workspace_toolkit.pptx import NS

from .conftest import fixture_parts, write_pptx
from .test_docx import docx_parts

EMU = 914_400  # per inch


# ------------------------------------------------------------------ pictures


def photo(width=2400, height=1600) -> Image.Image:
    """Photograph-like: smooth gradients with grain, so thousands of colours."""
    red = Image.linear_gradient("L").resize((width, height))
    green = Image.radial_gradient("L").resize((width, height))
    blue = Image.effect_noise((width, height), 40)
    return Image.merge("RGB", (red, green, blue))


def diagram(width=2400, height=1600) -> Image.Image:
    """Flat colours and sharp edges: a diagram or screenshot, not a photo."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for i in range(0, width, 200):
        draw.rectangle([i, 100, i + 120, height - 100], fill=(30, 90, 200), outline="black")
    # Noise in one corner keeps the file large, without making it a photo.
    image.paste(Image.effect_noise((600, 600), 90).convert("RGB").quantize(8).convert("RGB"))
    return image


def encode(image: Image.Image, kind: str, **options) -> bytes:
    out = io.BytesIO()
    image.save(out, kind, **options)
    return out.getvalue()


def rotated_jpeg() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees on display
    return encode(photo(), "JPEG", quality=95, exif=exif.tobytes())


# ---------------------------------------------------------------- packages


def pic(rid: str, inches_wide: float, inches_high: float, crop: str = "", shape_id: int = 10):
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="Picture {shape_id}"/><p:cNvPicPr/>'
        f'<p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{rid}"/>{crop}'
        "<a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm>"
        f'<a:off x="0" y="0"/><a:ext cx="{int(inches_wide * EMU)}" cy="{int(inches_high * EMU)}"/>'
        '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )


def deck(tmp_path, pictures: dict[str, bytes], body: str, *, overrides: str = ""):
    """A deck whose slide 1 holds `body`, with `pictures` as rId1, rId2, ..."""
    parts = fixture_parts()
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="{NS["r"]}/image" Target="../media/{name}"/>'
        for i, name in enumerate(pictures, start=1)
    )
    parts["ppt/slides/_rels/slide1.xml.rels"] = (
        f'<Relationships xmlns="{REL_NS}">{rels}</Relationships>'
    )
    parts["ppt/slides/slide1.xml"] = (
        f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}"><p:cSld><p:spTree>'
        f"<p:nvGrpSpPr/><p:grpSpPr/>{body}</p:spTree></p:cSld></p:sld>"
    )
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>", f'<Default Extension="jpg" ContentType="image/jpeg"/>{overrides}</Types>'
    )
    for name, data in pictures.items():
        parts[f"ppt/media/{name}"] = data
    return write_pptx(tmp_path / "deck.pptx", parts)


def squeeze(path, fmt=PPTX):
    report = compress(path, Settings(), fmt)
    return report, zipfile.ZipFile(path)


def size_of(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


# ------------------------------------------------------------------- tests


def test_a_photo_stored_as_png_becomes_a_smaller_jpeg(tmp_path):
    original = encode(photo(), "PNG")
    path = deck(
        tmp_path,
        {"photo.png": original},
        pic("rId1", 4, 8 / 3),
        overrides='<Override PartName="/ppt/media/photo.png" ContentType="image/png"/>',
    )
    report, out = squeeze(path)
    [done] = report["picturesCompressed"]
    assert done["part"] == "ppt/media/photo.png" and done["newPart"] == "ppt/media/photo.jpeg"
    assert "ppt/media/photo.png" not in out.namelist()
    data = out.read("ppt/media/photo.jpeg")
    assert data[:2] == b"\xff\xd8", "a JPEG"
    assert size_of(data) == (880, 587), "4 inches at 220 ppi"
    assert len(data) < len(original) / 10
    rels = out.read("ppt/slides/_rels/slide1.xml.rels").decode()
    assert 'Target="../media/photo.jpeg"' in rels
    types = out.read("[Content_Types].xml").decode()
    assert 'Extension="jpeg"' in types and "/ppt/media/photo.png" not in types
    assert report["bytesAfter"] < report["bytesBefore"]
    Package(path, Settings()).close()  # still a sound package


def test_a_diagram_stays_png_and_is_only_resized(tmp_path):
    path = deck(tmp_path, {"chart.png": encode(diagram(), "PNG")}, pic("rId1", 2, 4 / 3))
    report, out = squeeze(path)
    [done] = report["picturesCompressed"]
    assert done["newPart"] == "ppt/media/chart.png" and done["change"] == "resized"
    data = out.read("ppt/media/chart.png")
    assert data[:4] == b"\x89PNG" and size_of(data) == (440, 293)


def test_a_transparent_picture_stays_png(tmp_path):
    cutout = photo().convert("RGBA")
    cutout.putalpha(Image.linear_gradient("L").resize(cutout.size))
    path = deck(tmp_path, {"cutout.png": encode(cutout, "PNG")}, pic("rId1", 3, 2))
    report, out = squeeze(path)
    assert all(d["newPart"].endswith(".png") for d in report["picturesCompressed"])
    assert "ppt/media/cutout.png" in out.namelist()


def test_a_large_jpeg_is_resized_in_place(tmp_path):
    original = encode(photo(), "JPEG", quality=95)
    path = deck(tmp_path, {"phone.jpg": original}, pic("rId1", 3, 2))
    report, out = squeeze(path)
    [done] = report["picturesCompressed"]
    assert done["newPart"] == "ppt/media/phone.jpg"
    assert size_of(out.read("ppt/media/phone.jpg")) == (660, 440)


def test_a_crop_keeps_enough_pixels_for_what_is_shown(tmp_path):
    # Half the width is cropped away, so the visible half needs 660 px, and
    # the whole picture twice that.
    crop = '<a:srcRect l="25000" r="25000"/>'
    path = deck(
        tmp_path, {"phone.jpg": encode(photo(), "JPEG", quality=95)}, pic("rId1", 3, 2, crop)
    )
    _, out = squeeze(path)
    assert size_of(out.read("ppt/media/phone.jpg")) == (1320, 880)


@pytest.mark.parametrize(
    "why, pictures, body",
    [
        ("a rotation flag", {"a.jpg": rotated_jpeg()}, pic("rId1", 2, 2)),
        ("already small on disk", {"a.png": encode(photo(200, 100), "PNG")}, pic("rId1", 1, 0.5)),
        (
            "drawn larger than it is",
            {"a.jpg": encode(photo(), "JPEG", quality=95)},
            pic("rId1", 12, 8),
        ),
        (
            "also used as a shape fill",
            {"a.jpg": encode(photo(), "JPEG", quality=95)},
            pic("rId1", 2, 2)
            + '<p:sp><p:spPr><a:blipFill><a:blip r:embed="rId1"/></a:blipFill></p:spPr></p:sp>',
        ),
        (
            "inside a group",
            {"a.jpg": encode(photo(), "JPEG", quality=95)},
            "<p:grpSp><p:nvGrpSpPr/><p:grpSpPr/>" + pic("rId1", 2, 2) + "</p:grpSp>",
        ),
    ],
)
def test_pictures_it_cannot_be_sure_about_are_left_alone(tmp_path, why, pictures, body):
    path = deck(tmp_path, pictures, body)
    before = {name: zipfile.ZipFile(path).read(name) for name in zipfile.ZipFile(path).namelist()}
    report, out = squeeze(path)
    assert report["picturesCompressed"] == [], why
    for name, data in before.items():
        if name.startswith("ppt/media/"):
            assert out.read(name) == data, why


def test_a_picture_claiming_billions_of_pixels_is_refused_not_decoded(tmp_path):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    bomb = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 100_000, 100_000, 8, 2, 0, 0, 0))
        # Random padding: large enough to be worth compressing, and not so
        # compressible that the zip-bomb guard refuses the package first.
        + chunk(b"tEXt", b"pad\x00" + os.urandom(MIN_BYTES))
        + chunk(b"IDAT", zlib.compress(b"\x00" * 1000))
        + chunk(b"IEND", b"")
    )
    path = deck(tmp_path, {"bomb.png": bomb}, pic("rId1", 2, 2))
    report, out = squeeze(path)
    assert report["picturesCompressed"] == []
    assert report["skipped"]["unreadable"] == 1
    assert out.read("ppt/media/bomb.png") == bomb


def test_a_word_document_gets_the_same_treatment(tmp_path):
    drawing = (
        '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="2743200" cy="1828800"/>'
        '<wp:docPr id="1" name="Picture 1"/><a:graphic><a:graphicData '
        'uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
        '<pic:nvPicPr><pic:cNvPr id="1" name="Picture 1"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rIdPhoto"/><a:stretch><a:fillRect/></a:stretch>'
        '</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="2743200" cy="1828800"/>'
        '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
        '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr></w:p>'
    )
    parts = docx_parts(drawing, {"photo.png": encode(photo(), "PNG")})
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rIdPhoto" '
        f'Type="{NS["r"]}/image" Target="media/photo.png"/></Relationships>'
    )
    path = tmp_path / "worksheet.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    report, out = squeeze(path, DOCX)
    assert [d["newPart"] for d in report["picturesCompressed"]] == ["word/media/photo.jpeg"]
    assert size_of(out.read("word/media/photo.jpeg")) == (660, 440)
    rels = ElementTree.fromstring(out.read("word/_rels/document.xml.rels"))
    assert [r.get("Target") for r in rels] == ["media/photo.jpeg"]
    Package(path, Settings(), DOCX).close()


# ------------------------------------------------------------ through the app


def _post(monkeypatch, tmp_path, route, compress_header):
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from workspace_toolkit import web
    from workspace_toolkit.pipelines import resolve

    from .test_web import SESSION, configured

    sent = {}

    async def converted(root, manifest, google, progress, original_name=""):
        sent["size"] = (root / "result" / "converted.pptx").stat().st_size
        return {"status": "completed", "warnings": []}

    monkeypatch.setattr(web, "resolve", lambda name: replace(resolve("x.pptx"), convert=converted))
    path = deck(tmp_path, {"photo.png": encode(photo(), "PNG")}, pic("rId1", 4, 8 / 3))
    settings = configured()
    app = web.create_app(settings)
    client = TestClient(app, base_url=settings.base_url)
    import time

    cookie = {"access_token": "t", "expires": time.time() + 3600, "csrf": "c"}
    client.cookies.set(SESSION, app.state.auth.seal(cookie))
    headers = {
        "Content-Type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "X-Upload-Filename": "x.pptx",
        "X-CSRF-Token": "c",
    }
    first = client.post("/api/analyse", content=path.read_bytes(), headers=headers)
    if route == "analyse":
        headers["X-Compress-Pictures"] = compress_header
        return client.post("/api/analyse", content=path.read_bytes(), headers=headers), sent, path
    headers.update({"X-Source-Sha256": first.json()["sourceSha256"]})
    if compress_header:
        headers["X-Compress-Pictures"] = compress_header
    return client.post("/api/convert", content=path.read_bytes(), headers=headers), sent, path


def test_converting_with_smaller_pictures_sends_the_smaller_file(monkeypatch, tmp_path):
    response, sent, path = _post(monkeypatch, tmp_path, "convert", "1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [d["newPart"] for d in body["pictures"]["picturesCompressed"]] == [
        "ppt/media/photo.jpeg"
    ]
    assert "pictures_compressed" in [w["code"] for w in body["warnings"]]
    assert sent["size"] < path.stat().st_size / 5


def test_converting_without_it_changes_no_picture(monkeypatch, tmp_path):
    response, sent, path = _post(monkeypatch, tmp_path, "convert", "")
    body = response.json()
    assert "pictures" not in body
    assert sent["size"] > path.stat().st_size * 0.9


def test_checking_a_file_never_compresses_it(monkeypatch, tmp_path):
    response, _, _ = _post(monkeypatch, tmp_path, "analyse", "1")
    assert response.status_code == 200
    assert "pictures" not in response.json()
