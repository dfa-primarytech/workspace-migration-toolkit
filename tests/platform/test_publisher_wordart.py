"""WordArt recovered as editable text from Publisher's drawing records.

libmspub passes WordArt on as outlines only (PUB-001's title became two
purple lines). The records are built here, in Publisher's shape; nothing
comes from a real file.
"""

from __future__ import annotations

import struct

from workspace_toolkit.publisher_art import Prepared
from workspace_toolkit.publisher_slides import check, plan
from workspace_toolkit.publisher_wordart import placed, read

from .test_publisher_crop import container, drawing, record
from .test_publisher_slides import document, element, report, requests

PURPLE_BGR = 0xA26480  # Office stores 0x00BBGGRR: this is #8064a2


def wordart_shape(text: str, font: str = "Sassoon Primary", size: float = 44, bold=True) -> bytes:
    blobs = [(0xC0, (text + "\0").encode("utf-16-le")), (0xC5, (font + "\0").encode("utf-16-le"))]
    fixed = [
        (0xC3, round(size * 65536)),
        (0xFF, 0xFFFF0000 | (0x20 if bold else 0)),
        (0x181, PURPLE_BGR),
        (0x1C0, PURPLE_BGR),
    ]
    table = b"".join(struct.pack("<HI", 0x8000 | key, len(data)) for key, data in blobs)
    table += b"".join(struct.pack("<HI", key, value) for key, value in fixed)
    count = len(blobs) + len(fixed)
    return container(
        0xF004,
        record(0xF00A, struct.pack("<II", 1026, 0xA00), instance=136),
        record(0xF00B, table + b"".join(data for _, data in blobs), instance=count),
    )


def baseline(eid: str, z: int, y: float, parent: str) -> dict:
    def at(action, x):
        return {
            "action": action,
            "properties": {"svg:x": f"{x / 72:.4f}in", "svg:y": f"{y / 72:.4f}in"},
        }

    return element(
        eid,
        "path",
        z,
        None,
        parent=parent,
        style={"draw:fill": "none", "draw:stroke": "solid", "svg:stroke-color": "#8064a2"},
        geometry={
            "shapeKind": "path",
            "polygonIsRectangular": False,
            "points": [],
            "path": [at("M", 28), at("L", 278)],
        },
    )


def title_page() -> dict:
    layer = element(
        "el_1", "wrapper", 0, None, container={"kind": "layer", "isAuthoredGroup": False}
    )
    return document([layer, baseline("el_2", 1, 28, "el_1"), baseline("el_3", 2, 135, "el_1")])


def bundle(tmp_path, *shapes: bytes):
    folder = tmp_path / "bundle"
    folder.mkdir(exist_ok=True)
    (folder / "drawing.bin").write_bytes(drawing([], *shapes))
    return folder


def test_wordart_text_font_size_weight_and_colour_are_read():
    (art,) = read(drawing([], wordart_shape("Early Reading\r\n at St.Vincent's")))
    assert art.text == "Early Reading\nat St.Vincent's"
    assert (art.font, art.size, art.bold, art.italic) == ("Sassoon Primary", 44, True, False)
    assert art.colour == art.line == "#8064a2"


def test_wordart_is_placed_on_the_outline_drawn_in_its_colour(tmp_path):
    arts, notes = placed(bundle(tmp_path, wordart_shape("Title")), title_page())
    assert notes == []
    art, box = arts["el_1"]
    assert art.text == "Title"
    assert [round(v) for v in box] == [28, 28, 250, 107]


def test_wordart_with_nowhere_to_go_is_reported_with_its_words(tmp_path):
    empty = document([element("el_9", "text", 0, (0, 0, 10, 10), paragraphs=[])])
    arts, notes = placed(bundle(tmp_path, wordart_shape("Lost title")), empty)
    assert arts == {}
    assert notes[0]["code"] == "wordart-unplaced" and "Lost title" in notes[0]["message"]


def test_the_plan_writes_wordart_as_text_instead_of_its_outline(tmp_path):
    doc = title_page()
    prepared = Prepared()
    prepared.wordart, _ = placed(
        bundle(tmp_path, wordart_shape("Early Reading\r\nat St.Vincent's")), doc
    )
    result = plan(doc, prepared, title="Test", delete=["p"])
    assert check(result, existing=["p"]) == []
    assert requests(result, "createLine") == []  # the baselines are not drawn
    (inserted,) = requests(result, "insertText")
    assert inserted["text"] == "Early Reading\nat St.Vincent's"
    (styled,) = requests(result, "updateTextStyle")
    assert styled["style"]["fontFamily"] == "Andika" and styled["style"]["bold"] is True
    assert 6 <= styled["style"]["fontSize"]["magnitude"] <= 44
    assert styled["style"]["foregroundColor"]["opaqueColor"]["rgbColor"]["red"] == 0x80 / 255
    lines = report(result)
    assert lines["el_1"]["status"] == "SUBSTITUTED"
    assert {n["code"] for n in lines["el_1"]["notes"]} >= {"wordart-text", "font-substituted"}
    assert lines["el_2"]["notes"][0]["code"] == "wordart-outline"
