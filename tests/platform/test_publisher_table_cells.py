"""Empty table cells must not set the height of the row they are in.

Slides sets an unstyled empty cell in 18 pt text, so a row of tick boxes could
never be shorter than about 30 pt however small the planned text was. A booklet
of forms (a table of 15 rows planned at 307 pt) came out about 450 pt tall and
ran over the tables below it. An empty cell is now set in the size and font the
table's own text uses.
"""

from __future__ import annotations

from .test_publisher_slides import element, paragraph, planned, run


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


def blank_cells(result) -> dict[tuple[int, int], list[tuple[str, dict]]]:
    """The requests that touch each cell whose text is only a space put in and out."""
    seen: dict[tuple[int, int], list[tuple[str, dict]]] = {}
    for page in result.pages:
        for request in page:
            kind = next(iter(request))
            place = request[kind].get("cellLocation")
            if place:
                seen.setdefault((place["rowIndex"], place["columnIndex"]), []).append(
                    (kind, request[kind])
                )
    return {
        cell: steps
        for cell, steps in seen.items()
        if [k for k, _ in steps] == ["insertText", "updateTextStyle", "deleteText"]
        and steps[0][1]["text"] == " "
    }


def test_an_empty_cell_is_set_in_the_size_and_font_of_its_tables_text():
    rows = [
        [cell(0, 0, run("Name", font="Arial", size=8.0)), cell(0, 1)],
        [cell(1, 0), cell(1, 1, run("Date", font="Arial", size=8.0))],
    ]
    result = planned(_one_page(table_of(rows)))

    blank = blank_cells(result)
    assert set(blank) == {(0, 1), (1, 0)}, "only the empty cells"
    for (_, put), (_, style), (_, taken) in blank.values():
        assert put["insertionIndex"] == 0
        assert style["textRange"] == {"type": "FIXED_RANGE", "startIndex": 0, "endIndex": 1}
        assert style["style"]["fontSize"] == {"magnitude": 8.0, "unit": "PT"}
        assert style["style"]["fontFamily"] == "Arial"
        assert style["fields"] == "fontFamily,fontSize"
        assert taken["textRange"] == {"type": "FIXED_RANGE", "startIndex": 0, "endIndex": 1}


def test_the_commonest_size_wins_when_a_table_mixes_sizes():
    rows = [
        [cell(0, 0, run("Heading", size=14.0)), cell(0, 1, run("Note", size=8.0))],
        [cell(1, 0, run("One", size=8.0)), cell(1, 1)],
    ]
    result = planned(_one_page(table_of(rows)))

    assert blank_cells(result)[(1, 1)][1][1]["style"]["fontSize"]["magnitude"] == 8.0


def test_a_table_with_no_text_at_all_is_left_as_it_was():
    result = planned(_one_page(table_of([[cell(0, 0), cell(0, 1)], [cell(1, 0), cell(1, 1)]])))

    assert blank_cells(result) == {}


def _one_page(table: dict) -> dict:
    from .test_publisher_slides import document

    return document([table])
