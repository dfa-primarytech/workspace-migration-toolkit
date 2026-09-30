"""A picture above a table is measured against where the table really is (#168).

The pass for pictures floating just above a table took the table's columns to
start where the text column starts. An indented, centred, right-aligned or
floating table sits somewhere else, so a picture over its second column was
read against the wrong columns. The table's stated position now moves the
columns; a position that can't be worked out exactly leaves the pictures where
they are, reported as uncertain.
"""

from __future__ import annotations

from .test_docx import floating, para, placed_pictures, question_table

EMU = 635  # per twip
# A4_SECTION: 11906-twip page, 1440-twip margins, so the text column is 9026
# twips wide. Every table here is two 3000-twip columns, 6000 twips wide.
TEXT_WIDTH = 9026 * EMU
TABLE_WIDTH = 6000 * EMU
COLUMN = 3000 * EMU

IN_SECOND_COLUMN = [
    ["Can I count to ten?", 0],
    ["Can I count to ten?", 0],
    ["1.", 0],
    ["1.", 1],
]
NOWHERE = [
    ["Can I count to ten?", 0],
    ["Can I count to ten?", 0],
    ["1.", 0],
    ["1.", 0],
]


def table(properties):
    return question_table(rows=1, columns=(3000, 3000)).replace(
        "<w:tblPr/>", f"<w:tblPr>{properties}</w:tblPr>"
    )


def over_second_column(table_left, properties):
    """A picture 200000 EMU into the table's second column, well clear of
    both of its edges."""
    picture = floating(table_left + COLUMN + 200000, 100000, cx=1500000)
    return placed_pictures(para(picture) + table(properties))


def test_an_indented_table():
    report, cells = over_second_column(2000 * EMU, "<w:tblInd w:w='2000' w:type='dxa'/>")
    assert report["picturesPlaced"] == 1, report
    assert cells == IN_SECOND_COLUMN


def test_a_centred_table():
    left = (TEXT_WIDTH - TABLE_WIDTH) // 2
    report, cells = over_second_column(left, "<w:jc w:val='center'/>")
    assert report["picturesPlaced"] == 1, report
    assert cells == IN_SECOND_COLUMN


def test_a_right_aligned_table():
    report, cells = over_second_column(TEXT_WIDTH - TABLE_WIDTH, "<w:jc w:val='right'/>")
    assert report["picturesPlaced"] == 1, report
    assert cells == IN_SECOND_COLUMN


def test_a_floating_table_placed_against_the_margin():
    position = "<w:tblpPr w:horzAnchor='margin' w:vertAnchor='text' w:tblpX='2000'/>"
    report, cells = over_second_column(2000 * EMU, position)
    assert report["picturesPlaced"] == 1, report
    assert cells == IN_SECOND_COLUMN


def test_a_floating_table_placed_against_the_page():
    # The same position, measured from the paper's edge: 1440 twips further.
    position = "<w:tblpPr w:horzAnchor='page' w:vertAnchor='text' w:tblpX='3440'/>"
    report, cells = over_second_column(2000 * EMU, position)
    assert report["picturesPlaced"] == 1, report
    assert cells == IN_SECOND_COLUMN


def test_a_table_at_the_text_columns_start_is_placed_as_before():
    report, cells = over_second_column(0, "<w:jc w:val='left'/><w:tblInd w:w='0' w:type='dxa'/>")
    assert report["picturesPlaced"] == 1, report
    assert cells == IN_SECOND_COLUMN


def unknown_position(properties):
    # Over the first column if the table did start at the text column.
    picture = floating(200000, 100000, cx=1500000)
    return placed_pictures(para(picture) + table(properties))


def test_a_floating_table_aligned_rather_than_offset_is_reported():
    report, cells = unknown_position(
        "<w:tblpPr w:horzAnchor='margin' w:vertAnchor='text' w:tblpXSpec='center'/>"
    )
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert cells == NOWHERE


def test_an_indent_given_as_a_percentage_is_reported():
    report, cells = unknown_position("<w:tblInd w:w='500' w:type='pct'/>")
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert cells == NOWHERE


def test_a_right_to_left_table_is_reported():
    # Its columns run from the right, which this pass does not work out.
    report, cells = unknown_position("<w:bidiVisual/>")
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert cells == NOWHERE
