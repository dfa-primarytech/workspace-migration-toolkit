"""Windows metafile (WMF) clipart, drawn so Slides can take it as a PNG.

A Publisher booklet's clipart arrives as WMF, which Pillow cannot open off
Windows, so every such picture came out missing. These tests build tiny
metafiles in code; no real picture is involved.
"""

from __future__ import annotations

import struct

from PIL import Image
from workspace_toolkit.metafile import is_wmf, render_wmf
from workspace_toolkit.publisher_art import usable

# Record numbers, as the WMF specification gives them.
SET_WINDOW_ORG, SET_WINDOW_EXT = 0x020B, 0x020C
CREATE_BRUSH, CREATE_PEN = 0x02FC, 0x02FA
SELECT_OBJECT, DELETE_OBJECT = 0x012D, 0x01F0
POLYGON, POLYPOLYGON, RECTANGLE = 0x0324, 0x0538, 0x041B
TEXT_OUT = 0x0521


def record(function: int, *words: int) -> bytes:
    body = b"".join(struct.pack("<h" if w < 0 else "<H", w) for w in words)
    return struct.pack("<IH", 3 + len(words), function) + body


def colour(r: int, g: int, b: int) -> tuple[int, int]:
    """A COLORREF as the two 16-bit words a record stores."""
    return r | (g << 8), b


def brush(rgb: tuple[int, int, int], style: int = 0) -> bytes:
    low, high = colour(*rgb)
    return record(CREATE_BRUSH, style, low, high, 0)


def pen(rgb: tuple[int, int, int], style: int = 0, width: int = 1) -> bytes:
    low, high = colour(*rgb)
    return record(CREATE_PEN, style, width, 0, low, high)


def points(*pairs: tuple[int, int]) -> list[int]:
    return [v for pair in pairs for v in pair]


def metafile(records: list[bytes], *, placeable: tuple[int, int, int, int] | None = None) -> bytes:
    body = b"".join(records) + struct.pack("<IH", 3, 0)
    total_words = (18 + len(body)) // 2
    header = struct.pack("<HHHIHIH", 1, 9, 0x0300, total_words, 8, 20, 0)
    prefix = b""
    if placeable:
        prefix = struct.pack("<IHhhhhHIH", 0x9AC6CDD7, 0, *placeable, 96, 0, 0)
    return prefix + header + body


# A 100 x 100 window with a red square (20..80) filled and a blue pen.
SQUARE = [
    record(SET_WINDOW_ORG, 0, 0),
    record(SET_WINDOW_EXT, 100, 100),
    brush((255, 0, 0)),
    pen((0, 0, 255), style=5),  # no outline
    record(SELECT_OBJECT, 0),
    record(SELECT_OBJECT, 1),
    record(POLYGON, 4, *points((20, 20), (80, 20), (80, 80), (20, 80))),
]


def test_a_filled_polygon_is_drawn_in_its_colour_on_a_clear_background():
    image = render_wmf(metafile(SQUARE))

    assert image is not None
    assert image.mode == "RGBA"
    w, h = image.size
    assert image.getpixel((w // 2, h // 2)) == (255, 0, 0, 255)
    assert image.getpixel((2, 2))[3] == 0, "outside the shape must stay transparent"


def test_a_picture_keeps_the_shape_of_its_window():
    wide = [record(SET_WINDOW_ORG, 0, 0), record(SET_WINDOW_EXT, 100, 400), *SQUARE[2:]]
    image = render_wmf(metafile(wide))

    assert image is not None
    assert image.width == 4 * image.height or abs(image.width - 4 * image.height) <= 4


def test_a_window_with_a_negative_extent_runs_the_way_it_says():
    # Publisher writes origin 100 and extent -100 for y: logical 100 is the TOP,
    # so a square at y 80..100 sits in the top fifth of the picture.
    flipped = [
        record(SET_WINDOW_ORG, 100, 0),
        record(SET_WINDOW_EXT, -100, 100),
        brush((255, 0, 0)),
        pen((0, 0, 0), style=5),
        record(SELECT_OBJECT, 0),
        record(SELECT_OBJECT, 1),
        record(POLYGON, 4, *points((10, 100), (90, 100), (90, 80), (10, 80))),
    ]
    image = render_wmf(metafile(flipped))

    assert image is not None
    w, h = image.size
    assert image.getpixel((w // 2, h // 10)) == (255, 0, 0, 255), "the square belongs at the top"
    assert image.getpixel((w // 2, h * 9 // 10))[3] == 0


def test_a_shape_with_a_hollow_brush_is_not_filled():
    hollow = [*SQUARE[:2], brush((255, 0, 0), style=1), *SQUARE[3:]]
    image = render_wmf(metafile(hollow))

    assert image is not None
    w, h = image.size
    assert image.getpixel((w // 2, h // 2))[3] == 0


def test_two_rings_of_a_polypolygon_leave_the_inner_one_open():
    outer = ((10, 10), (90, 10), (90, 90), (10, 90))
    inner = ((40, 40), (60, 40), (60, 60), (40, 60))
    ring = [
        *SQUARE[:5],
        record(SELECT_OBJECT, 1),
        record(POLYPOLYGON, 2, 4, 4, *points(*outer), *points(*inner)),
    ]
    image = render_wmf(metafile(ring))

    assert image is not None
    w, h = image.size
    assert image.getpixel((w // 2, h // 2))[3] == 0, "the hole must show through"
    assert image.getpixel((w // 8 + 4, h // 2)) == (255, 0, 0, 255)


def test_a_deleted_object_slot_is_reused_by_the_next_one_created():
    # Slot 0 is freed and the green brush takes it, so selecting 0 gives green.
    reused = [
        record(SET_WINDOW_ORG, 0, 0),
        record(SET_WINDOW_EXT, 100, 100),
        brush((255, 0, 0)),
        record(DELETE_OBJECT, 0),
        brush((0, 255, 0)),
        pen((0, 0, 0), style=5),
        record(SELECT_OBJECT, 0),
        record(SELECT_OBJECT, 1),
        record(POLYGON, 4, *points((0, 0), (100, 0), (100, 100), (0, 100))),
    ]
    image = render_wmf(metafile(reused))

    assert image is not None
    assert image.getpixel((image.width // 2, image.height // 2)) == (0, 255, 0, 255)


def test_a_placeable_header_is_read_as_well():
    placed = metafile(SQUARE[2:], placeable=(0, 0, 100, 100))
    image = render_wmf(placed)

    assert image is not None
    assert is_wmf(placed)
    assert image.getpixel((image.width // 2, image.height // 2)) == (255, 0, 0, 255)


def test_a_picture_that_needs_text_is_refused_rather_than_drawn_wrongly():
    with_text = [*SQUARE, record(TEXT_OUT, 2, 0x4142, 0, 10, 10)]

    assert render_wmf(metafile(with_text)) is None


def test_junk_and_truncated_files_give_nothing_and_do_not_raise():
    good = metafile(SQUARE)

    assert render_wmf(b"") is None
    assert render_wmf(b"not a metafile at all, just text") is None
    cut = render_wmf(good[: len(good) // 2])
    assert cut is None or isinstance(cut, Image.Image)
    assert not is_wmf(b"\x89PNG\r\n\x1a\n")


def test_an_enormous_window_still_gives_a_bounded_picture():
    huge = [record(SET_WINDOW_ORG, 0, 0), record(SET_WINDOW_EXT, 30000, 30000), *SQUARE[2:]]
    image = render_wmf(metafile(huge))

    assert image is not None
    assert max(image.size) <= 2000


def test_a_metafile_asset_becomes_a_png_slides_can_take(tmp_path):
    (tmp_path / "pic.wmf").write_bytes(metafile(SQUARE))
    asset = {"id": "asset_1", "filename": "pic.wmf", "mimeType": "image/wmf"}

    picture, reason = usable(asset, tmp_path, tmp_path)

    assert reason is None
    assert picture is not None
    assert picture.mime == "image/png"
    assert [n["code"] for n in picture.notes] == ["picture-converted"]
    with Image.open(picture.path) as saved:
        assert saved.size == (picture.width, picture.height)


def test_a_metafile_that_cannot_be_drawn_is_still_reported_missing(tmp_path):
    (tmp_path / "pic.wmf").write_bytes(metafile([*SQUARE, record(TEXT_OUT, 2, 0x4142, 0, 1, 1)]))
    asset = {"id": "asset_1", "filename": "pic.wmf", "mimeType": "image/wmf"}

    picture, reason = usable(asset, tmp_path, tmp_path)

    assert picture is None
    assert "could not be read" in reason
