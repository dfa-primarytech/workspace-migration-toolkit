"""Text in a table cell that an author pushed past a picture with spaces.

A badge's logo sits over the left of its cell and the text was moved clear of
it by typing spaces in front of every line. Slides draws those spaces in a
narrower face than Publisher did, so the text landed under the logo (ticket
658976, the visitor badges). The spaces are replaced by an indent that clears
the picture whatever font is used.
"""

from __future__ import annotations

from .test_publisher_slides import (
    document,
    element,
    image,
    paragraph,
    pictures,
    planned,
    requests,
    run,
)

GAP = 8.0


def cell(row, column, *paragraphs):
    return {
        "row": row,
        "column": column,
        "rowSpan": 1,
        "columnSpan": 1,
        "covered": False,
        "paragraphs": list(paragraphs),
    }


def badge(*paragraphs, bounds=(100, 50, 200, 80), column_width=200):
    rows = [
        {
            "index": 0,
            "eventIndex": 0,
            "heightIsMinimum": False,
            "isHeader": False,
            "sourceProperties": {"librevenge:row-height": f"{bounds[3]}pt"},
            "cells": [cell(0, 0, *paragraphs)],
        }
    ]
    columns = [{"width": {"points": column_width, "sourceValue": column_width, "sourceUnit": "pt"}}]
    return element("el_t", "table", 0, bounds, table={"columns": columns, "rows": rows})


def texts(result):
    return [t["text"] for t in requests(result, "insertText")]


def indents(result):
    return [
        s["style"]["indentStart"]["magnitude"] if "indentStart" in s["style"] else 0.0
        for s in requests(result, "updateParagraphStyle")
    ]


def test_text_pushed_past_a_picture_by_spaces_is_indented_clear_of_it(tmp_path):
    table = badge(
        paragraph(run("          Visitor      ")),
        paragraph(run("      Mr N. Collings   ")),
    )
    logo = image("el_p", 1, (104, 60, 60, 60), "a")
    result = planned(document([table, logo]), pictures(tmp_path, a=(10, 10)))

    assert texts(result) == ["Visitor\nMr N. Collings"]
    needed = (104 + 60 + GAP) - (100 + 7.2)
    assert all(start >= needed - 0.5 for start in indents(result)), indents(result)


def test_a_cell_with_no_picture_over_it_keeps_its_spaces(tmp_path):
    table = badge(paragraph(run("          Visitor      ")))
    far = image("el_p", 1, (400, 60, 60, 60), "a")
    result = planned(document([table, far]), pictures(tmp_path, a=(10, 10)))

    assert texts(result) == ["          Visitor      "]


def test_text_that_was_not_padded_is_left_as_it_was(tmp_path):
    table = badge(paragraph(run("Visitor")))
    logo = image("el_p", 1, (104, 60, 60, 60), "a")
    result = planned(document([table, logo]), pictures(tmp_path, a=(10, 10)))

    assert texts(result) == ["Visitor"]
    assert indents(result) == [0.0]


def test_a_picture_drawn_behind_the_table_is_cleared_too(tmp_path):
    table = badge(paragraph(run("          Visitor      ")))
    table["zIndex"] = 5
    logo = image("el_p", 1, (104, 60, 60, 60), "a")
    result = planned(document([logo, table]), pictures(tmp_path, a=(10, 10)))

    assert texts(result) == ["Visitor"]
    assert indents(result)[0] >= (104 + 60 + GAP) - (100 + 7.2) - 0.5
