"""A picture over a table is moved into a column only if it fits inside it (#55).

The pass for pictures floating just above a table chose a column from the
picture's centre, so a picture crossing a column boundary was put in whichever
column held its centre, then shrunk to fit. Like the table-geometry pass, it now
moves a picture only when the whole picture lies inside one column, and reports
the rest as uncertain.
"""

from __future__ import annotations

from workspace_toolkit.docs import transform

from .test_docx import A4_SECTION, document, floating, para, parse_xml, q, question_table
from .test_docx_placement import positioned

# A4_SECTION's left margin, 1440 twips, in EMU.
MARGIN = 1440 * 635


def run(body):
    root = parse_xml(document(body + A4_SECTION))
    report = transform(root)
    return report, len(list(root.iter(q("wp", "anchor"))))


def test_a_picture_straddling_two_columns_is_left_and_reported():
    # Codex's reproduction: the two 5752-twip columns meet at 3652520 EMU, and
    # this picture runs from 3000000 to 4500000.
    report, floating_left = run(
        para(floating(3000000, 100000, cx=1500000)) + question_table(rows=1)
    )
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert floating_left == 1


def test_a_picture_inside_one_column_is_still_placed():
    report, floating_left = run(
        para(floating(3700000, 100000, cx=1500000)) + question_table(rows=1)
    )
    assert report["picturesPlaced"] == 1
    assert report["picturesGeometryUncertain"] == 0
    assert floating_left == 0


def test_a_margin_anchored_picture_straddling_two_columns_is_left_and_reported():
    # A left-margin strip starts at the paper's edge, so this is the same
    # picture as above, measured from there.
    picture = floating(MARGIN + 3000000, 100000, cx=1500000, frame_h="leftMargin")
    report, floating_left = run(para(picture) + question_table(rows=1))
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert floating_left == 1


def test_one_straddling_picture_leaves_the_whole_group_in_place():
    # Which row each picture belongs to is read from the whole stack, so
    # placing only the pictures that fit could put them in the wrong rows.
    body = (
        para(floating(200000, 100000))
        + para(floating(3000000, 100000, cx=1500000))
        + question_table(rows=1)
    )
    report, floating_left = run(body)
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert report["picturesUnplaced"] == 1
    assert floating_left == 2


def test_a_straddling_picture_is_counted_once_when_the_table_can_be_measured():
    # The table is pinned to the page with exact rows, so the table-geometry
    # pass also sees this picture over it, and must not count it again.
    # On the page it crosses 2540000, where the table's first two columns
    # meet; against the text column it crosses 1905000, the same boundary.
    table = positioned([("", "<w:tc><w:p/></w:tc>" * 3)])
    picture = floating(2300000, 700000, cx=600000, frame_h="page", frame_v="page")
    report, floating_left = run(para(picture) + table)
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert floating_left == 1
