"""Empty table cells must not set the height of the row they are in.

Slides sets an unstyled empty cell in 18 pt text, so a row of tick boxes could
never be shorter than about 30 pt however small the planned text was. A booklet
of forms (a table of 15 rows planned at 307 pt) came out about 450 pt tall and
ran over the tables below it. An empty cell is now set in the size and font the
table's own text uses.
"""

from __future__ import annotations

from .test_publisher_slides import element, paragraph, planned, requests, run


def cell(row: int, column: int, *runs: dict) -> dict:
    return {
        "row": row,
        "column": column,
        "rowSpan": 1,
        "columnSpan": 1,
        "covered": False,
        "paragraphs": [paragraph(*runs)],
    }


def table_of(rows: list[list[dict]], frame=(10, 10, 300, 200)) -> dict:
    body = [
        {
            "index": i,
            "eventIndex": 0,
            "heightIsMinimum": False,
            "isHeader": False,
            "cells": cells,
        }
        for i, cells in enumerate(rows)
    ]
    columns = [{"width": {"points": 150, "sourceValue": 150, "sourceUnit": "pt"}}] * len(rows[0])
    return element("el_1", "table", 0, frame, table={"columns": columns, "rows": body})


def cell_styles(result) -> dict[tuple[int, int], dict]:
    found = {}
    for style in requests(result, "updateTextStyle"):
        place = style.get("cellLocation")
        if place and style["textRange"]["type"] == "ALL":
            found[(place["rowIndex"], place["columnIndex"])] = style
    return found


def test_an_empty_cell_is_set_in_the_size_and_font_of_its_tables_text():
    rows = [
        [cell(0, 0, run("Name", font="Arial", size=8.0)), cell(0, 1)],
        [cell(1, 0), cell(1, 1, run("Date", font="Arial", size=8.0))],
    ]
    result = planned(_one_page(table_of(rows)))

    styled = cell_styles(result)
    assert set(styled) == {(0, 1), (1, 0)}, "only the empty cells"
    for style in styled.values():
        assert style["style"]["fontSize"] == {"magnitude": 8.0, "unit": "PT"}
        assert style["style"]["fontFamily"] == "Arial"
        assert style["fields"] == "fontFamily,fontSize"


def test_the_commonest_size_wins_when_a_table_mixes_sizes():
    rows = [
        [cell(0, 0, run("Heading", size=14.0)), cell(0, 1, run("Note", size=8.0))],
        [cell(1, 0, run("One", size=8.0)), cell(1, 1)],
    ]
    result = planned(_one_page(table_of(rows)))

    assert cell_styles(result)[(1, 1)]["style"]["fontSize"]["magnitude"] == 8.0


def test_a_table_with_no_text_at_all_is_left_as_it_was():
    result = planned(_one_page(table_of([[cell(0, 0), cell(0, 1)], [cell(1, 0), cell(1, 1)]])))

    assert cell_styles(result) == {}


def _one_page(table: dict) -> dict:
    from .test_publisher_slides import document

    return document([table])
