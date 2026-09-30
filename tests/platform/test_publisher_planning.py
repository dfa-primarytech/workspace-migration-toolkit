"""Planning faults found in the 2026-09-29 audit (#105, #106, #107, #110): each
stopped a whole Publisher file, or lost content without a note. Every
document is built here; nothing comes from a real file."""

from __future__ import annotations

import dataclasses

import pytest
from workspace_toolkit.publisher_art import Prepared
from workspace_toolkit.publisher_inline import MARK, marks, prepared
from workspace_toolkit.publisher_wordart import placed as wordart_placed
from workspace_toolkit.units import Frame

from .test_publisher_inline import files, inline_shape, jpeg
from .test_publisher_slides import (
    document,
    element,
    image,
    paragraph,
    pictures,
    planned,
    report,
    requests,
    run,
    text_box,
)
from .test_publisher_table_fit import WORDS, rectangle, table
from .test_publisher_wordart import baseline, bundle, wordart_shape

# ------------------------------------------------------------------ #105


@pytest.mark.parametrize("bounds", [(20, 100, 300, 0), (20, 100, 0, 40)])
def test_a_rule_with_no_height_or_width_beside_a_table_does_not_stop_the_plan(bounds):
    result = planned(document([table((20, 20, 300, 60), WORDS), rectangle("el_2", bounds)]))
    (line,) = requests(result, "createLine")
    x, y, width, height = bounds
    props = line["elementProperties"]
    assert (props["transform"]["translateX"], props["transform"]["translateY"]) == (x, y)
    assert props["size"]["width"]["magnitude"] == pytest.approx(max(width, 0.01), abs=0.5)
    assert report(result)["el_2"]["notes"][0]["code"] == "drawn-as-line"
    assert requests(result, "createShape") == []  # the table is not a shape either


def test_a_flat_shape_with_no_outline_is_reported_as_showing_nothing():
    flat = rectangle("el_2", (20, 100, 300, 0))
    flat["source"]["styleProperties"] = {"draw:fill": "solid", "draw:stroke": "none"}
    result = planned(document([flat]))
    assert requests(result, "createLine") == []
    assert report(result)["el_2"]["status"] == "IGNORED"


def test_a_frame_with_no_height_still_has_its_corners():
    assert Frame(100, 0, 50, 10).corners() == [(0, 10), (100, 10), (100, 10), (0, 10)]


def test_a_turned_frame_keeps_its_corners_without_a_transform():
    corners = Frame(100, 0, 0, 0, 90).corners()
    assert [(round(x, 6), round(y, 6)) for x, y in corners[:2]] == [(0, 50), (0, -50)]


def test_a_picture_with_no_size_is_reported_not_drawn(tmp_path):
    prepared_ = pictures(tmp_path, a1=(10, 10))
    doc = document([image("el_1", 0, (20, 20, 50, 0), "a1"), text_box("el_2", 1, (0, 0, 10, 10))])
    result = planned(doc, prepared_)
    assert requests(result, "createImage") == []
    line = report(result)["el_1"]
    assert line["status"] == "UNSUPPORTED"
    assert line["notes"][0]["code"] == "picture-no-size"


# ------------------------------------------------------------------ #106


def test_a_table_in_a_nested_group_is_never_sent_to_be_grouped(tmp_path):
    prepared_ = pictures(tmp_path, a1=(10, 10))
    authored = {"kind": "layer", "isAuthoredGroup": True}
    outer = element("el_1", "group", 0, None, container=authored)
    inner = element("el_2", "group", 1, None, parent="el_1", container=authored)
    small = table((0, 40, 50, 30), "Year 4")
    small |= {"id": "el_5", "parentId": "el_2"}
    doc = document(
        [
            outer,
            inner,
            small | {"zIndex": 2},
            image("el_3", 3, (60, 0, 10, 10), "a1", parent="el_2"),
            image("el_4", 4, (80, 0, 10, 10), "a1", parent="el_1"),
        ]
    )
    result = planned(doc, prepared_)
    assert all("wmt_el_1" not in g["childrenObjectIds"] for g in requests(result, "groupObjects"))
    assert requests(result, "groupObjects") == []
    lines = report(result)
    assert lines["el_1"]["notes"][0]["code"] == "group-not-kept"
    assert lines["el_2"]["notes"][0]["code"] == "group-not-kept"


# ------------------------------------------------------------------ #110


def wordart_in_a_group(tmp_path, text: str):
    authored = {"kind": "layer", "isAuthoredGroup": True}
    layer = {"kind": "layer", "isAuthoredGroup": False}
    doc = document(
        [
            element("el_0", "group", 0, None, container=authored),
            element("el_1", "wrapper", 1, None, parent="el_0", container=layer),
            baseline("el_2", 2, 28, "el_1"),
            baseline("el_3", 3, 135, "el_1"),
            rectangle("el_4", (20, 200, 100, 40)) | {"parentId": "el_0", "zIndex": 4},
        ]
    )
    arts, _ = wordart_placed(bundle(tmp_path, wordart_shape(text)), doc)
    return doc, Prepared(wordart=arts)


def test_wordart_in_an_authored_group_is_grouped_with_the_rest(tmp_path):
    doc, prepared_ = wordart_in_a_group(tmp_path, "Title")
    result = planned(doc, prepared_)
    (grouped,) = requests(result, "groupObjects")
    assert "wmt_el_1" in grouped["childrenObjectIds"]
    assert report(result)["el_0"]["status"] == "NATIVE"


def test_a_stray_control_character_in_wordart_is_dropped_not_fatal(tmp_path):
    doc, prepared_ = wordart_in_a_group(tmp_path, "Title")
    art, box = prepared_.wordart["el_1"]
    prepared_.wordart["el_1"] = (dataclasses.replace(art, text="Ti\x01tle"), box)
    result = planned(doc, prepared_)  # check() finds nothing Slides would drop
    (inserted,) = requests(result, "insertText")
    assert inserted["text"] == "Title"


# ------------------------------------------------------------------ #107


def cover_box() -> dict:
    return text_box(
        "el_1",
        0,
        (50, 40, 200, 120),
        paragraph(run("A book")),
        paragraph(run(MARK)),
    )


def test_marks_in_a_text_box_are_found():
    assert list(marks(document([cover_box()]))) == [("el_1", -1, -1, 1)]


def test_a_picture_set_in_a_text_box_is_reported_as_missing(tmp_path):
    doc = document([cover_box()])
    bundle_ = files(tmp_path, [inline_shape(1, 10, 40, 50)], [jpeg(40, 50)])
    found, notes = prepared(bundle_, doc, {"assets": []}, tmp_path / "art")
    assert notes == [] and list(found) == [("el_1", -1, -1, 1)]
    result = planned(doc, Prepared(inline=found))
    assert all(MARK not in t["text"] for t in requests(result, "insertText"))
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "inline-picture-missing" in codes


def test_a_text_box_mark_counts_against_the_pictures_found(tmp_path):
    # One recovered picture, two marks (a table's and a text box's): not paired.
    covered = table((50, 200, 100, 40), "Book")
    covered["table"]["rows"][0]["cells"][0]["paragraphs"].append(paragraph(run(MARK)))
    covered["id"] = "el_2"
    doc = document([cover_box(), covered])
    bundle_ = files(tmp_path, [inline_shape(1, 10, 40, 50)], [jpeg(40, 50)])
    found, notes = prepared(bundle_, doc, {"assets": []}, tmp_path / "art")
    assert found == {}
    assert [n["code"] for n in notes] == ["inline-pictures-unplaced"]
