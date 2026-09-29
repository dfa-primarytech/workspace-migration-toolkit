"""Tables keep to the page: Slides grows a row to its text, so text laid out
Google's way can push a Publisher table past the page (PUB-002's page 3). A
table may grow into free space; only past that is its text brought closer,
then made smaller, as a text box's is."""

from __future__ import annotations

from .test_publisher_slides import document, element, paragraph, planned, report, requests, run

WORDS = "Pupils develop a love of reading and read widely for pleasure every day. "


def table(bounds, text: str, row_height: float = 20.0) -> dict:
    cell = {
        "row": 0,
        "column": 0,
        "rowSpan": 1,
        "columnSpan": 1,
        "covered": False,
        "paragraphs": [paragraph(run(text, font="Calibri", size=12))],
    }
    rows = [{"index": 0, "height": {"points": row_height}, "cells": [cell]}]
    columns = [{"width": {"points": bounds[2]}}]
    return element("el_1", "table", 1, bounds, table={"columns": columns, "rows": rows})


def frame_box() -> dict:
    """A page border the table sits in, as PUB-002's pages have."""
    return rectangle("el_0", (10, 10, 400, 72))


def rectangle(eid: str, bounds) -> dict:
    geometry = {"shapeKind": "rectangle", "polygonIsRectangular": True, "points": [], "path": []}
    style = {"draw:fill": "none", "draw:stroke": "solid", "svg:stroke-color": "#000000"}
    return element(eid, "shape", 0, bounds, style=style, geometry=geometry)


def sizes(result) -> set[float]:
    return {s["style"]["fontSize"]["magnitude"] for s in requests(result, "updateTextStyle")}


def spacings(result) -> set[float | None]:
    return {p["style"].get("lineSpacing") for p in requests(result, "updateParagraphStyle")}


def test_a_table_that_would_run_past_its_box_is_fitted_and_says_so():
    result = planned(document([frame_box(), table((20, 20, 300, 60), WORDS * 4)]))
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "text-spacing-tightened" in codes
    assert any(s is not None and s < 100 for s in spacings(result))
    if "text-made-smaller" in codes:
        assert all(size < 12 for size in sizes(result))


def test_a_table_with_room_below_is_left_to_grow():
    result = planned(document([table((20, 20, 300, 60), WORDS * 4)]))
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "text-spacing-tightened" not in codes and "text-made-smaller" not in codes
    assert sizes(result) == {12}


def test_something_below_a_table_is_room_it_cannot_take():
    below = rectangle("el_2", (20, 90, 300, 20))
    result = planned(document([table((20, 20, 300, 60), WORDS * 4), below]))
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "text-spacing-tightened" in codes


def test_a_table_that_fits_as_it_is_is_not_touched():
    result = planned(document([frame_box(), table((20, 20, 300, 60), "Year 4")]))
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "text-spacing-tightened" not in codes and sizes(result) == {12}
