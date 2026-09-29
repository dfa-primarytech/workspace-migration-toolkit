"""Recovering Publisher picture crops from its drawing records (drawing.bin).

The records are built here, in the shape Publisher writes them (with its four
extra bytes after drawing containers); nothing comes from a real file.
"""

from __future__ import annotations

import json
import struct

import pytest
from PIL import Image
from workspace_toolkit.publisher_art import prepare
from workspace_toolkit.publisher_crop import Crop, crops, read
from workspace_toolkit.publisher_slides import check, plan

from .test_publisher_slides import document, image, report, requests


def record(kind: int, body: bytes, instance: int = 0, version: int = 0) -> bytes:
    head = (instance << 4) | version
    return struct.pack("<HHI", head, kind, len(body)) + body


def container(kind: int, *children: bytes) -> bytes:
    return record(kind, b"".join(children), version=0xF)


def fbse(size: int) -> bytes:
    body = bytearray(36)
    struct.pack_into("<I", body, 20, size)
    return record(0xF007, bytes(body))


def fixed(fraction: float) -> int:
    return round(fraction * 65536) & 0xFFFFFFFF


def picture_shape(blip: int, top=0.0, bottom=0.0, left=0.0, right=0.0) -> bytes:
    props = [(0x4104, blip)]
    for key, value in ((0x100, top), (0x101, bottom), (0x102, left), (0x103, right)):
        if value:
            props.append((key, fixed(value)))
    fopt = b"".join(struct.pack("<HI", k, v) for k, v in props)
    return container(
        0xF004,
        record(0xF00A, struct.pack("<II", 1025, 0xA00)),
        record(0xF00B, fopt, instance=len(props)),
    )


def drawing(sizes: list[int], *shapes: bytes) -> bytes:
    dgg = container(0xF000, record(0xF006, bytes(16)), container(0xF001, *map(fbse, sizes)))
    dg = container(0xF002, record(0xF008, bytes(8)), container(0xF003, *shapes))
    return dgg + b"\0\0\0\0" + dg + b"\0\0\0\0"  # Publisher's extra four bytes


def bundle_with(tmp_path, blob: bytes, assets: list[dict]):
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True, exist_ok=True)
    (bundle / "drawing.bin").write_bytes(blob)
    return bundle, {"assets": assets}


def asset(aid: str, size: int, width: int, height: int) -> dict:
    return {
        "id": aid,
        "filename": f"assets/{aid}.png",
        "mimeType": "image/png",
        "byteLength": size,
        "pixelWidth": width,
        "pixelHeight": height,
    }


BANNER = asset("banner", 83338, 873, 421)
# Its two placements in PUB-001: a thin strip on page 1, trimmed further on page 4.
STRIP = dict(top=0.0711, bottom=0.6783, left=0.0715, right=0.0467)
SHORT = dict(top=0.0711, bottom=0.6783, left=0.0715, right=0.5492)


def two_banners():
    return document(
        [image("el_8", 0, (27.3, 148.7, 367.4, 50.3), "banner")],
        [image("el_19", 0, (77.4, 117.3, 297.6, 94.8), "banner")],
    )


def test_the_records_are_read_with_publishers_extra_bytes():
    stored, shapes = read(drawing([2930, 83346], picture_shape(2, **STRIP)))
    assert stored == [2930, 83346]
    (shape,) = shapes
    assert shape.blip == 2
    assert shape.crop.bottom == pytest.approx(0.6783, abs=1e-4)


def test_one_picture_cropped_two_ways_is_matched_to_each_placement(tmp_path):
    blob = drawing([83346], picture_shape(1, **STRIP), picture_shape(1, **SHORT))
    bundle, assets = bundle_with(tmp_path, blob, [BANNER])
    found, notes = crops(bundle, two_banners(), assets)
    assert notes == []
    assert found["el_8"].right == pytest.approx(0.0467, abs=1e-4)
    assert found["el_19"].right == pytest.approx(0.5492, abs=1e-4)


def test_the_pairing_does_not_depend_on_the_records_order(tmp_path):
    blob = drawing([83346], picture_shape(1, **SHORT), picture_shape(1, **STRIP))
    bundle, assets = bundle_with(tmp_path, blob, [BANNER])
    found, _ = crops(bundle, two_banners(), assets)
    assert found["el_8"].right == pytest.approx(0.0467, abs=1e-4)  # the frame decides


def test_a_crop_that_does_not_fit_its_frame_is_not_applied(tmp_path):
    blob = drawing([83346], picture_shape(1, **STRIP))
    bundle, assets = bundle_with(tmp_path, blob, [BANNER])
    square = document([image("el_1", 0, (0, 0, 100, 100), "banner")])
    found, notes = crops(bundle, square, assets)
    assert found == {} and notes[0]["code"] == "crop-unmatched"


def test_without_drawing_records_or_with_damaged_ones_nothing_is_cropped(tmp_path):
    assert crops(tmp_path, two_banners(), {"assets": [BANNER]}) == ({}, [])
    whole = drawing([83346], picture_shape(1, **STRIP))
    for broken in (whole[:40], whole[:-30], b"\xff" * 64, b""):
        bundle, assets = bundle_with(tmp_path, broken, [BANNER])
        found, _ = crops(bundle, two_banners(), assets)
        assert found == {}


def test_impossible_crops_are_refused():
    assert not Crop(0.6, 0.5, 0, 0).valid  # more than all of it
    assert not Crop(-0.1, 0, 0, 0).valid  # Publisher can pad outwards; not handled
    assert Crop(0.1, 0.2, 0.3, 0.4).valid


def test_the_cropped_part_is_what_slides_receives(tmp_path):
    blob = drawing([83346], picture_shape(1, **STRIP), picture_shape(1, **SHORT))
    bundle, assets = bundle_with(tmp_path, blob, [BANNER])
    Image.new("RGB", (873, 421), "purple").save(bundle / "assets" / "banner.png")
    doc = two_banners()
    found, _ = crops(bundle, doc, assets)
    prepared = prepare(doc, assets, bundle, tmp_path / "art", crops=found)
    strip = prepared.cropped["el_8"]
    assert (strip.width, strip.height) == (770, 105)
    assert strip.width / strip.height == pytest.approx(367.4 / 50.3, rel=0.03)
    result = plan(doc, prepared, title="Test", delete=["p"])
    assert check(result, existing=["p"]) == []
    urls = [r["url"] for r in requests(result, "createImage")]
    assert urls == ["wmt-picture:crop_el_8", "wmt-picture:crop_el_19"]
    codes = [n["code"] for n in report(result)["el_8"]["notes"]]
    assert "picture-cropped" in codes and "picture-stretched" not in codes
    assert json.dumps(result.as_dict(tmp_path))  # the plan still saves
