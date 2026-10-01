"""The Publisher → Slides renderer, offline (Publisher step 2, DECISIONS.md 2026-09-28).

Every document here is built in the test from the parser's schema: nothing
comes from a real Publisher file. Nothing talks to Google; `check()` stands
in for what the Slides API would refuse, and the geometry is checked by
applying each transform the way Slides does.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest
from PIL import Image
from workspace_toolkit import publisher_art
from workspace_toolkit.publisher_art import Picture, Prepared, prepare, subpaths
from workspace_toolkit.publisher_slides import (
    PICTURE,
    bind,
    check,
    line_request,
    plan,
    utf16,
)
from workspace_toolkit.units import Frame, apply, length_points

A5 = (420.944882, 595.275591)
PAGE = "wmt_page_0001"


# ------------------------------------------------------------------ builders


def element(eid: str, kind: str, z: int, bounds=None, **extra) -> dict:
    result = {
        "id": eid,
        "type": kind,
        "pageIndex": extra.pop("page", 0),
        "bounds": None
        if bounds is None
        else dict(zip(("x", "y", "width", "height"), bounds, strict=True), unit="pt"),
        "rotationDegrees": extra.pop("rotation", None),
        "zIndex": z,
        "parentId": extra.pop("parent", None),
        "visible": extra.pop("visible", True),
        "source": {
            "callback": "test",
            "eventIndex": z,
            "endEventIndex": z,
            "properties": extra.pop("props", {}),
            "styleProperties": extra.pop("style", {"draw:fill": "none", "draw:stroke": "none"}),
        },
        "compatibility": {"status": "NATIVE", "basis": "parser-candidate", "evidence": "test"},
        "warnings": extra.pop("warnings", []),
    }
    result.update(extra)
    return result


def run(text: str, font="Calibri", size=12.0, bold=False, colour="#000000", **props) -> dict:
    items = []
    for i, word in enumerate(text.split(" ")):
        if i:
            items.append({"kind": "space", "value": " "})
        if word:
            items.append({"kind": "text", "value": word})
    return {
        "index": 0,
        "eventIndex": 0,
        "text": text,
        "items": items,
        "style": {
            "fontFamily": font,
            "fontSizePoints": size,
            "bold": bold,
            "italic": False,
            "underline": None,
            "color": colour,
            "language": "en",
            "country": "GB",
        },
        "implicit": False,
        "sourceProperties": props,
    }


def paragraph(*runs: dict, align="left", **props) -> dict:
    return {
        "index": 0,
        "eventIndex": 0,
        "style": {"alignment": align, "lineHeight": None},
        "listLevel": 0,
        "implicit": False,
        "sourceProperties": {"fo:text-align": align, **props},
        "runs": list(runs),
    }


def text_box(eid, z, bounds, *paragraphs, **extra) -> dict:
    return element(eid, "text", z, bounds, paragraphs=list(paragraphs), **extra)


def image(eid, z, bounds, asset, **extra) -> dict:
    x, y, w, h = bounds
    outline = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    return element(
        eid,
        "image",
        z,
        bounds,
        image={
            "assetId": asset,
            "route": "bitmapFillShape",
            "shapeKind": "polygon",
            "polygonIsRectangular": True,
            "polygon": [{"x": px, "y": py} for px, py in outline],
            "path": [],
        },
        **extra,
    )


def path(eid, z, commands, style, **extra) -> dict:
    def command(action, x=None, y=None, **more):
        props = {"librevenge:path-action": action, **more}
        if x is not None:
            props |= {"svg:x": f"{x / 72:.4f}in", "svg:y": f"{y / 72:.4f}in"}
        return {"action": action, "properties": props}

    return element(
        eid,
        "path",
        z,
        None,
        style=style,
        geometry={
            "shapeKind": "path",
            "polygonIsRectangular": False,
            "points": [],
            "path": [command(*c) if isinstance(c, tuple) else command(c) for c in commands],
        },
        **extra,
    )


def document(*pages: list[dict], size=A5) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "pages": [
            {
                "id": f"page_{i + 1:04d}",
                "index": i,
                "kind": "page",
                "width": size[0],
                "height": size[1],
                "unit": "pt",
                "elements": [{**e, "pageIndex": i} for e in elements],
                "warnings": [],
            }
            for i, elements in enumerate(pages)
        ],
    }


def pictures(tmp_path: Path, **sizes: tuple[int, int]) -> Prepared:
    prepared = Prepared()
    for key, (w, h) in sizes.items():
        file = tmp_path / f"{key}.png"
        Image.new("RGB", (w, h), (200, 30, 30)).save(file)
        prepared.pictures[key] = Picture(key, file, w, h, "image/png")
    return prepared


def requests(result, kind: str) -> list[dict]:
    return [r[kind] for page in result.pages for r in page if kind in r]


def planned(doc, prepared=None):
    result = plan(doc, prepared or Prepared(), title="Test", delete=["p"])
    assert check(result, existing=["p"]) == []
    return result


def report(result) -> dict[str, dict]:
    return {e["elementId"]: e for e in result.report["elements"]}


def drawn_corners(body: dict) -> list[tuple[float, float]]:
    props = body["elementProperties"]
    w, h = props["size"]["width"]["magnitude"], props["size"]["height"]["magnitude"]
    return [apply(props["transform"], p) for p in ((0, 0), (w, 0), (w, h), (0, h))]


def close(a, b, tolerance=1e-3) -> bool:
    return all(
        abs(p - q) < tolerance for u, v in zip(a, b, strict=True) for p, q in zip(u, v, strict=True)
    )


# ------------------------------------------------------------------ units


@pytest.mark.parametrize(
    "text, points",
    [("0.3937in", 28.3464), ("12pt", 12), ("2.54cm", 72), ("240*", 12), ("10", 10), ("50%", None)],
)
def test_lengths_are_read_in_points(text, points):
    value = length_points(text)
    assert (value is None) if points is None else math.isclose(value, points, rel_tol=1e-4)


@pytest.mark.parametrize("rotation", [0, 30, 90, 200, 333])
def test_a_turned_frame_is_drawn_where_its_outline_is(rotation):
    frame = Frame(120, 40, 200, 300, rotation)
    outline = frame.corners()
    recovered = Frame.from_outline(outline)
    assert recovered is not None
    assert recovered.width == pytest.approx(120, abs=1e-3)
    assert recovered.height == pytest.approx(40, abs=1e-3)
    assert recovered.rotation % 360 == pytest.approx(rotation % 360, abs=1e-3)
    # An element of another natural size, stretched into the frame.
    transform = frame.transform(60, 90)
    drawn = [apply(transform, p) for p in ((0, 0), (60, 0), (60, 90), (0, 90))]
    assert close(drawn, outline)


def test_counter_clockwise_means_the_top_edge_rises():
    top_left, top_right, *_ = Frame(100, 10, 0, 0, 30).corners()
    assert top_right[1] < top_left[1]  # y points down the page


# ------------------------------------------------------------------ the document


def test_the_presentation_keeps_the_publications_page_size_and_order():
    result = planned(document([], [], []))
    width = result.create["pageSize"]["width"]["magnitude"]
    height = result.create["pageSize"]["height"]["magnitude"]
    assert (width, height) == pytest.approx(A5)
    slides = [r["createSlide"] for r in result.setup if "createSlide" in r]
    assert [s["insertionIndex"] for s in slides] == [0, 1, 2]
    assert all(s["slideLayoutReference"] == {"predefinedLayout": "BLANK"} for s in slides)
    assert {"deleteObject": {"objectId": "p"}} in result.setup


def test_pages_of_different_sizes_are_reported():
    doc = document([], [])
    doc["pages"][1]["width"] = 842
    result = planned(doc)
    assert "page-sizes-differ" in [w["code"] for w in result.report["warnings"]]


def test_everything_is_reported_and_paint_order_is_kept(tmp_path):
    prepared = pictures(tmp_path, a1=(100, 100))
    elements = [
        image("el_2", 2, (10, 10, 50, 50), "a1"),
        text_box("el_1", 1, (0, 0, 200, 40), paragraph(run("Hello"))),
        element("el_3", "unknown", 3, (0, 0, 1, 1)),
        text_box("el_4", 4, (0, 0, 10, 10), paragraph(run("hidden")), visible=False),
    ]
    result = planned(document(elements), prepared)
    made = [
        next(iter(r.values()))["objectId"]
        for r in result.pages[0]
        if next(iter(r)) in {"createShape", "createImage"}
    ]
    assert made == ["wmt_el_1", "wmt_el_2"]  # lowest first: the last drawn is on top
    lines = report(result)
    assert set(lines) == {"el_1", "el_2", "el_3", "el_4"}
    assert lines["el_3"]["status"] == "UNSUPPORTED"
    assert lines["el_4"]["status"] == "IGNORED"
    assert "Google Slides" in result.report["basis"]


# ------------------------------------------------------------------ text


def test_text_is_inserted_once_then_styled_run_by_run_in_utf16():
    box = text_box(
        "el_1",
        0,
        (10, 20, 300, 100),
        paragraph(run("Hi 😀 ", bold=True), run("there", colour="#00b2ad")),
        paragraph(run("Second", size=18)),
    )
    result = planned(document([box]))
    inserted = requests(result, "insertText")
    assert [i["text"] for i in inserted] == ["Hi 😀 there\nSecond"]
    styles = requests(result, "updateTextStyle")
    ranges = [(s["textRange"]["startIndex"], s["textRange"]["endIndex"]) for s in styles]
    first = utf16("Hi 😀 ")
    assert first == 6  # the emoji is two code units
    assert ranges == [(0, first), (first, first + 5), (first + 6, first + 12)]
    assert styles[0]["style"]["bold"] is True
    assert styles[1]["style"]["foregroundColor"]["opaqueColor"]["rgbColor"][
        "blue"
    ] == pytest.approx(0xAD / 255)
    assert styles[2]["style"]["fontSize"] == {"magnitude": 18, "unit": "PT"}


def test_sassoon_is_written_as_andika_and_reported():
    box = text_box(
        "el_1", 0, (0, 0, 100, 50), paragraph(run("Sounds", font="SassoonPrimaryInfant"))
    )
    result = planned(document([box]))
    assert requests(result, "updateTextStyle")[0]["style"]["fontFamily"] == "Andika"
    assert report(result)["el_1"]["status"] == "SUBSTITUTED"
    fonts = {f["name"]: f for f in result.report["fonts"]}
    assert fonts["SassoonPrimaryInfant"]["replacement"] == "Andika"


def test_paragraph_layout_is_carried_over():
    hanging = paragraph(
        run("Point"),
        **{"fo:margin-left": "0.3937in", "fo:text-indent": "-0.3937in", "fo:line-height": "115%"},
    )
    centred = paragraph(run("Title"), align="center", **{"fo:margin-right": "1in"})
    result = planned(document([text_box("el_1", 0, (0, 0, 300, 100), hanging, centred)]))
    first, second = requests(result, "updateParagraphStyle")
    assert first["style"]["indentStart"]["magnitude"] == pytest.approx(28.3464, rel=1e-4)
    assert first["style"]["indentFirstLine"]["magnitude"] == 0
    assert first["style"]["lineSpacing"] == 115
    assert second["style"]["alignment"] == "CENTER"
    assert second["style"]["indentEnd"]["magnitude"] == 72


def test_breaks_and_empty_paragraphs():
    line_break = run("a")
    line_break["items"] += [{"kind": "lineBreak"}, {"kind": "tab"}, {"kind": "text", "value": "b"}]
    doc = document(
        [
            text_box(
                "el_1",
                0,
                (0, 0, 100, 100),
                paragraph(line_break),
                paragraph(run("", size=30)),
                paragraph(run("c")),
                paragraph(run("")),
            )
        ]
    )
    result = planned(doc)
    assert requests(result, "insertText")[0]["text"] == "a\u000b\tb\n\nc"
    # The empty middle paragraph keeps its 30 pt height through its break.
    styles = requests(result, "updateTextStyle")
    assert any(
        s["textRange"] == {"type": "FIXED_RANGE", "startIndex": 5, "endIndex": 6} for s in styles
    )
    assert any(s["style"].get("fontSize", {}).get("magnitude") == 30 for s in styles)


def test_publishers_paragraph_marks_are_not_sent():
    # The reader leaves Publisher's own paragraph mark, a carriage return, at
    # the end of each paragraph's text. Slides drops it on insert, so sending
    # it made every later range overrun the text (the first live run).
    marked = [run("First\r"), run("Second\r"), run("\r")]
    box = text_box(
        "el_1",
        0,
        (0, 0, 100, 100),
        paragraph(marked[0]),
        paragraph(marked[1]),
        paragraph(marked[2]),
    )
    result = planned(document([box]))
    assert requests(result, "insertText")[0]["text"] == "First\nSecond"
    only_mark = text_box("el_2", 0, (0, 0, 100, 100), paragraph(run("\r")))
    assert not requests(planned(document([only_mark])), "insertText")


def test_the_checker_refuses_characters_slides_would_drop():
    result = planned(document([text_box("el_1", 0, (0, 0, 10, 10), paragraph(run("ok")))]))
    result.pages[0].append(
        {"insertText": {"objectId": "wmt_el_1", "insertionIndex": 0, "text": "bad\r"}}
    )
    assert any("characters Slides drops" in p for p in check(result, existing=["p"]))


def test_an_empty_text_box_is_still_placed():
    result = planned(document([text_box("el_1", 0, (0, 0, 100, 100))]))
    assert requests(result, "createShape") and not requests(result, "insertText")


# ------------------------------------------------------------------ pictures


def test_a_picture_is_stretched_to_its_frame_as_publisher_draws_it(tmp_path):
    prepared = pictures(tmp_path, a1=(800, 400))
    result = planned(document([image("el_1", 0, (20, 30, 300, 50), "a1")]), prepared)
    (body,) = requests(result, "createImage")
    assert body["url"] == PICTURE + "a1"
    size = body["elementProperties"]["size"]
    # Slides would fit a picture inside a differently shaped size: give it its own shape…
    assert size["height"]["magnitude"] / size["width"]["magnitude"] == pytest.approx(0.5)
    # …and let the transform stretch it to the frame.
    assert close(drawn_corners(body), [(20, 30), (320, 30), (320, 80), (20, 80)])
    assert "picture-stretched" in [n["code"] for n in report(result)["el_1"]["notes"]]


def test_a_turned_picture_is_placed_by_its_outline(tmp_path):
    prepared = pictures(tmp_path, a1=(200, 100))
    frame = Frame(200, 100, 210, 300, 30)
    outline = frame.corners()
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    turned = image("el_1", 0, (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)), "a1")
    turned["image"]["polygon"] = [{"x": x, "y": y} for x, y in outline + outline[:1]]
    turned["image"]["polygonIsRectangular"] = False
    turned["rotationDegrees"] = 30
    turned["warnings"] = [{"code": "rotation-from-outline", "message": "…"}]
    result = planned(document([turned]), prepared)
    (body,) = requests(result, "createImage")
    assert close(drawn_corners(body), outline)


def test_a_picture_that_could_not_be_read_leaves_a_marked_space(tmp_path):
    prepared = Prepared(refused={"a1": "This picture could not be read."})
    result = planned(document([image("el_1", 0, (0, 0, 100, 100), "a1")]), prepared)
    assert not requests(result, "createImage")
    assert "could not be converted" in requests(result, "insertText")[0]["text"]
    line = report(result)["el_1"]
    assert line["status"] == "UNSUPPORTED" and line["notes"][0]["code"] == "picture-missing"


def test_pictures_slides_would_refuse_are_converted_or_made_smaller(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    Image.new("RGB", (40, 30), "blue").save(bundle / "assets" / "b.bmp")
    Image.new("RGB", (400, 300), "red").save(bundle / "assets" / "big.png")
    (bundle / "assets" / "junk.png").write_bytes(b"not a picture")
    monkeypatch.setattr(publisher_art, "SLIDES_MAX_PIXELS", 10_000)
    out = tmp_path / "out"
    out.mkdir()

    def asset(aid, name, mime, w, h):
        return {
            "id": aid,
            "filename": f"assets/{name}",
            "mimeType": mime,
            "byteLength": 1,
            "pixelWidth": w,
            "pixelHeight": h,
        }

    bmp, notes = publisher_art.usable(asset("b", "b.bmp", "image/bmp", 40, 30), bundle, out)
    assert bmp and bmp.mime == "image/png" and bmp.path.suffix == ".png" and notes is None
    assert bmp.notes[0]["code"] == "picture-converted"
    big, _ = publisher_art.usable(asset("g", "big.png", "image/png", 400, 300), bundle, out)
    assert big and big.width * big.height <= 10_000
    assert big.notes[0]["code"] == "picture-reduced"
    junk, reason = publisher_art.usable(
        asset("j", "junk.png", "image/png", None, None), bundle, out
    )
    assert junk is None and reason


# ------------------------------------------------------------------ drawings


RULE = {
    "draw:fill": "none",
    "draw:stroke": "solid",
    "svg:stroke-color": "#8064a2",
    "svg:stroke-width": "0.0099in",
}


def test_ruled_lines_become_editable_lines_and_a_path_that_draws_nothing_is_reported():
    # PUB-001's shape: two horizontal rules, and a filled path of no area.
    rules = [("M", 28, 28), ("L", 278, 28), ("M", 28, 135), ("L", 278, 135)]
    doc = document(
        [
            path("el_1", 0, [*rules[:2], "Z", "Z", *rules[2:], "Z"], {"draw:fill": "gradient"}),
            path("el_2", 1, rules, RULE),
        ]
    )
    result = planned(doc)
    lines = requests(result, "createLine")
    assert len(lines) == 2
    assert close(drawn_corners(lines[0])[::2], [(28, 28), (278, 28)], 0.02)
    weight = requests(result, "updateLineProperties")[0]["lineProperties"]["weight"]
    assert weight["magnitude"] == pytest.approx(0.7128, rel=1e-3)
    assert requests(result, "groupObjects")[0]["childrenObjectIds"] == ["wmt_el_2_0", "wmt_el_2_1"]
    lines_report = report(result)
    assert lines_report["el_1"]["status"] == "IGNORED"
    assert lines_report["el_2"]["status"] == "SUBSTITUTED"


@pytest.mark.parametrize(
    "start, end", [((100, 50), (20, 80)), ((10, 10), (10, 90)), ((5, 5), (50, 1))]
)
def test_a_line_points_the_way_it_was_drawn(start, end):
    body = line_request("wmt_line_1", PAGE, start, end)["createLine"]
    corners = drawn_corners(body)
    assert close([corners[0], corners[2]], [start, end], 0.02)


def test_a_filled_drawing_becomes_a_picture(tmp_path):
    arrow = [
        ("M", 10, 40),
        ("L", 60, 40),
        ("L", 60, 10),
        ("L", 90, 50),
        ("L", 60, 90),
        ("L", 60, 60),
        ("L", 10, 60),
        "Z",
    ]
    style = {"draw:fill": "solid", "draw:fill-color": "#ff0000", "draw:stroke": "none"}
    doc = document([path("el_1", 0, arrow, style)])
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    prepared = prepare(doc, {"assets": []}, bundle, tmp_path / "art")
    drawn = prepared.drawn["el_1"]
    x, y, w, h = drawn.box
    assert x < 10 < 90 < x + w and y < 10 < 90 < y + h
    picture = Image.open(drawn.picture.path)
    assert picture.getpixel((picture.width // 2, picture.height // 2))[3] > 0  # filled
    assert picture.getpixel((0, 0))[3] == 0  # transparent outside
    result = planned(doc, prepared)
    assert requests(result, "createImage")[0]["url"] == PICTURE + "drawn_el_1"
    assert report(result)["el_1"]["status"] == "FLATTENED"


def test_curves_and_arcs_are_followed():
    curve = [
        {"action": "M", "properties": {"svg:x": "0in", "svg:y": "0in"}},
        {
            "action": "C",
            "properties": {
                "svg:x": "1in",
                "svg:y": "0in",
                "svg:x1": "0in",
                "svg:y1": "1in",
                "svg:x2": "1in",
                "svg:y2": "1in",
            },
        },
        {
            "action": "A",
            "properties": {
                "svg:x": "3in",
                "svg:y": "0in",
                "svg:rx": "1in",
                "svg:ry": "1in",
                "librevenge:sweep": "true",
            },
        },
    ]
    (piece,) = subpaths(curve)
    assert piece.curved
    assert piece.points[0] == (0, 0) and piece.points[-1] == pytest.approx((216, 0))
    # A half circle from x=72 to x=216 bulges a full radius away.
    arc = piece.points[-publisher_art.CURVE_STEPS :]
    assert max(abs(p[1]) for p in arc) == pytest.approx(72, rel=0.01)


def test_rectangles_and_ellipses_are_slides_shapes():
    style = {"draw:fill": "solid", "draw:fill-color": "#00ff00", "draw:stroke": "none"}
    ellipse = element(
        "el_2",
        "shape",
        1,
        None,
        style=style,
        props={"svg:cx": "1in", "svg:cy": "1in", "svg:rx": "0.5in", "svg:ry": "0.25in"},
        geometry={"shapeKind": "ellipse", "polygonIsRectangular": False, "points": [], "path": []},
    )
    square = element(
        "el_1",
        "shape",
        0,
        (0, 0, 50, 50),
        style=style,
        geometry={"shapeKind": "rectangle", "polygonIsRectangular": True, "points": [], "path": []},
    )
    result = planned(document([square, ellipse]))
    kinds = [s["shapeType"] for s in requests(result, "createShape")]
    assert kinds == ["RECTANGLE", "ELLIPSE"]
    assert close(drawn_corners(requests(result, "createShape")[1])[::2], [(36, 54), (108, 90)])
    fill = requests(result, "updateShapeProperties")[0]["shapeProperties"]["shapeBackgroundFill"]
    assert fill["solidFill"]["color"]["rgbColor"]["green"] == 1


# ------------------------------------------------------------------ border art


def test_border_art_is_combined_into_one_picture(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    Image.new("RGB", (10, 10), "green").save(bundle / "assets" / "tile.png")
    assets = {
        "assets": [
            {
                "id": "t",
                "filename": "assets/tile.png",
                "mimeType": "image/png",
                "byteLength": 1,
                "pixelWidth": 10,
                "pixelHeight": 10,
            }
        ]
    }
    tiles = [
        image(
            f"el_{i + 2}",
            i + 1,
            (x, 20, 10, 10),
            "t",
            parent="el_1",
            warnings=[{"code": "probable-border-art", "message": "…"}],
        )
        for i, x in enumerate(range(20, 120, 10))
    ]
    for tile in tiles:
        tile["image"]["route"] = "drawGraphicObject"
    layer = element(
        "el_1", "wrapper", 0, None, container={"kind": "layer", "isAuthoredGroup": False}
    )
    doc = document([layer, *tiles])
    prepared = prepare(doc, assets, bundle, tmp_path / "art")
    result = planned(doc, prepared)
    (body,) = requests(result, "createImage")
    assert body["url"] == PICTURE + "border_0000_el_1"
    assert close(drawn_corners(body)[::2], [(20, 20), (120, 30)])
    lines = report(result)
    assert all(lines[t["id"]]["status"] == "FLATTENED" for t in tiles)
    composed = Image.open(prepared.borders["border_0000_el_1"].picture.path).convert("RGB")
    assert composed.getpixel((composed.width // 2, composed.height // 2)) == (0, 128, 0)


# ------------------------------------------------------------------ tables and groups


def test_a_table_is_built_cell_by_cell():
    def cell(row, column, text, **extra):
        return {
            "row": row,
            "column": column,
            "rowSpan": 1,
            "columnSpan": 1,
            "covered": False,
            "paragraphs": [paragraph(run(text))],
            **extra,
        }

    rows = [
        {
            "index": 0,
            "eventIndex": 0,
            "heightIsMinimum": False,
            "isHeader": False,
            "sourceProperties": {"librevenge:row-height": "1in"},
            "cells": [cell(0, 0, "Wide", columnSpan=2), {**cell(0, 1, ""), "covered": True}],
        },
        {
            "index": 1,
            "eventIndex": 0,
            "heightIsMinimum": False,
            "isHeader": False,
            "cells": [
                cell(1, 0, "A", sourceProperties={"fo:background-color": "#ffff00"}),
                cell(1, 1, "B"),
            ],
        },
    ]
    columns = [
        {"width": {"points": 100, "sourceValue": 100, "sourceUnit": "pt"}},
        {"width": {"points": 20, "sourceValue": 20, "sourceUnit": "pt"}},
    ]
    table = element(
        "el_1", "table", 0, (10, 10, 120, 144), table={"columns": columns, "rows": rows}
    )
    result = planned(document([table]))
    (made,) = requests(result, "createTable")
    assert (made["rows"], made["columns"]) == (2, 2)
    widths = [
        c["tableColumnProperties"]["columnWidth"]["magnitude"]
        for c in requests(result, "updateTableColumnProperties")
    ]
    assert widths == [100, 32]  # the narrow one widened, and reported
    (height,) = requests(result, "updateTableRowProperties")
    assert height["tableRowProperties"]["minRowHeight"]["magnitude"] == 72
    assert requests(result, "mergeTableCells")[0]["tableRange"]["columnSpan"] == 2
    cells = [
        (t["cellLocation"]["rowIndex"], t["cellLocation"]["columnIndex"], t["text"])
        for t in requests(result, "insertText")
    ]
    assert cells == [(0, 0, "Wide"), (1, 0, "A"), (1, 1, "B")]
    assert requests(result, "updateTableCellProperties")
    # Publisher's default grid, thin and black, not Google's grey one.
    (borders,) = requests(result, "updateTableBorderProperties")
    assert borders["borderPosition"] == "ALL" and "tableRange" not in borders
    line = borders["tableBorderProperties"]
    assert line["tableBorderFill"]["solidFill"]["alpha"] == 1
    assert line["weight"] == {"magnitude": 0.75, "unit": "PT"} and line["dashStyle"] == "SOLID"
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "column-widened" in codes and "table-borders" in codes


def test_authored_groups_are_grouped_and_a_group_with_a_table_is_reported(tmp_path):
    prepared = pictures(tmp_path, a1=(10, 10))
    group = element("el_1", "group", 0, None, container={"kind": "layer", "isAuthoredGroup": True})
    other = element("el_4", "group", 3, None, container={"kind": "layer", "isAuthoredGroup": True})
    table = element(
        "el_6",
        "table",
        5,
        (0, 0, 50, 50),
        parent="el_4",
        table={
            "columns": [{"width": None}],
            "rows": [
                {
                    "index": 0,
                    "eventIndex": 0,
                    "heightIsMinimum": False,
                    "isHeader": False,
                    "cells": [],
                }
            ],
        },
    )
    doc = document(
        [
            group,
            image("el_2", 1, (0, 0, 10, 10), "a1", parent="el_1"),
            image("el_3", 2, (20, 0, 10, 10), "a1", parent="el_1"),
            other,
            image("el_5", 4, (40, 0, 10, 10), "a1", parent="el_4"),
            table,
        ]
    )
    result = planned(doc, prepared)
    (grouped,) = requests(result, "groupObjects")
    assert grouped == {"groupObjectId": "wmt_el_1", "childrenObjectIds": ["wmt_el_2", "wmt_el_3"]}
    lines = report(result)
    assert lines["el_1"]["status"] == "NATIVE"
    assert lines["el_4"]["notes"][0]["code"] == "group-not-kept"


def test_content_repeated_on_every_page_is_reported_as_probable_master(tmp_path):
    prepared = pictures(tmp_path, logo=(10, 10))
    doc = document(
        [image("el_1", 0, (5, 5, 20, 20), "logo"), text_box("el_2", 1, (0, 50, 10, 10))],
        [image("el_3", 0, (5, 5, 20, 20), "logo")],
    )
    result = planned(doc, prepared)
    lines = report(result)
    assert "probable-master" in [n["code"] for n in lines["el_1"]["notes"]]
    assert "probable-master" not in [n["code"] for n in lines["el_2"]["notes"]]
    assert len(requests(result, "createImage")) == 2  # reported, never removed


# ------------------------------------------------------------------ sending


def test_links_are_bound_page_by_page_and_every_one_is_needed(tmp_path):
    prepared = pictures(tmp_path, a1=(10, 10), a2=(10, 10))
    doc = document([image("el_1", 0, (0, 0, 9, 9), "a1")], [image("el_2", 0, (0, 0, 9, 9), "a2")])
    result = planned(doc, prepared)
    assert result.keys_for(0) == ["a1"] and result.keys_for(1) == ["a2"]
    assert set(result.pictures) == {"a1", "a2"}
    bound = bind(result.pages[0], {"a1": "https://storage.example/a1?sig"})
    assert bound[0]["createImage"]["url"].startswith("https://")
    assert result.pages[0][0]["createImage"]["url"] == PICTURE + "a1"  # the plan is untouched
    with pytest.raises(KeyError):
        bind(result.pages[1], {})
    assert any("no link" in p for p in check(result, existing=["p"], bound=True))


def test_the_checker_catches_what_google_would_refuse():
    result = planned(document([text_box("el_1", 0, (0, 0, 10, 10), paragraph(run("abc")))]))
    page = result.pages[0]
    page.append(page[0])  # the same ID twice
    page.append(
        {
            "updateTextStyle": {
                "objectId": "wmt_el_1",
                "fields": "bold",
                "style": {"bold": True},
                "textRange": {"type": "FIXED_RANGE", "startIndex": 2, "endIndex": 9},
            }
        }
    )
    page.append({"createShape": {"objectId": "bad id!", "shapeType": "TEXT_BOX"}})
    problems = check(result, existing=["p"])
    assert any("made twice" in p for p in problems)
    assert any("outside" in p for p in problems)
    assert any("invalid ID" in p for p in problems)


# ------------------------------------------------------------------ PUB-001


PUB001 = os.environ.get("PUBLISHER_FIXTURE_PUB001")
PARSER = os.environ.get("PUBLISHER_PARSER_BIN") or shutil.which("publisher-parser")


@pytest.mark.skipif(not (PUB001 and PARSER), reason="PUB-001 and the parser are supplied privately")
def test_pub001_plans_cleanly(tmp_path):
    bundle = tmp_path / "bundle"
    subprocess.run([PARSER, PUB001, str(bundle)], check=True, capture_output=True)  # noqa: S603  # nosec B603
    doc = json.loads((bundle / "document.json").read_text(encoding="utf-8"))
    assets = json.loads((bundle / "assets.json").read_text(encoding="utf-8"))
    result = plan(doc, prepare(doc, assets, bundle, tmp_path / "art"), title="PUB-001")
    assert check(result) == []
    assert len(result.slides) == 4
    # Two of its text frames hold only Publisher's paragraph marks: empty, so
    # no font needs replacing in them.
    assert result.report["statusCounts"] == {"NATIVE": 14, "SUBSTITUTED": 6, "IGNORED": 2}
    assert len(requests(result, "createImage")) == 12
    assert len(requests(result, "createLine")) == 2


def test_the_readers_notes_are_kept_and_marked_as_the_readers():
    reader = {"code": "implicit-text-frame", "message": "text arrived outside a text frame"}
    box = text_box("el_1", 0, (10, 10, 100, 40), paragraph(run("Hi")), warnings=[reader])
    notes = report(planned(document([box])))["el_1"]["notes"]
    kept = [n for n in notes if n["code"] == "implicit-text-frame"]
    assert kept == [{**reader, "source": "reader"}]


def codes_of(result, eid) -> set[str]:
    return {n["code"] for n in report(result)[eid]["notes"]}


def test_a_font_slides_lacks_is_said_to_be_shown_in_arial_not_replaced():
    # A booklet in Amasis MT Pro was told "A font was replaced; see the
    # fonts", but the fonts list had no replacement: it is drawn in Arial (#178).
    box = text_box("el_1", 0, (0, 0, 100, 50), paragraph(run("Title", font="Amasis MT Pro")))
    result = planned(document([box]))
    line = report(result)["el_1"]
    assert line["status"] == "SUBSTITUTED"
    assert codes_of(result, "el_1") == {"font-missing"}
    [missing] = line["notes"]
    assert "Amasis MT Pro" in missing["message"] and "Arial" in missing["message"]


def test_symbol_text_drawn_in_arial_is_flagged_for_its_characters():
    box = text_box("el_1", 0, (0, 0, 100, 50), paragraph(run("", font="Symbol")))
    result = planned(document([box]))
    assert codes_of(result, "el_1") == {"font-symbol-missing"}
    [note] = report(result)["el_1"]["notes"]
    assert "wrong characters" in note["message"]


def test_a_box_mixing_a_replaced_and_a_missing_font_says_both():
    box = text_box(
        "el_1",
        0,
        (0, 0, 200, 50),
        paragraph(run("Sounds", font="SassoonPrimaryInfant"), run(" more", font="Amasis MT Pro")),
    )
    assert codes_of(planned(document([box])), "el_1") == {"font-substituted", "font-missing"}


def test_a_font_slides_has_gets_no_font_note():
    box = text_box("el_1", 0, (0, 0, 100, 50), paragraph(run("Plain", font="Calibri")))
    result = planned(document([box]))
    assert report(result)["el_1"]["status"] == "NATIVE"
    assert codes_of(result, "el_1") == set()
