"""#134: page coordinates repeat on every page.

The geometry pass compared a picture's page position with every positioned
table in the document, so a picture on a later page, at the spot a table fills
on an earlier one, was moved into that table and counted as placed. A picture
and a table now have to be shown to share a page first; where that cannot be
shown, the picture stays where it is and the report says so.
"""

from __future__ import annotations

from workspace_toolkit.docs import transform

from .test_docx import (
    A4_SECTION,
    NOT_ADJACENT_TO_TABLE,
    PICTURE,
    anchor,
    converted_job,
    document,
    floating,
    offset,
    para,
    parse_xml,
    positioned_table,
    q,
    question_table,
)

# Inside the table's first cell, on the page it fills.
OVER_THE_TABLE = anchor(
    PICTURE, h=("page", offset(800000)), v=("page", offset(700000)), cx=500000, cy=500000
)
TABLE = positioned_table(1000, 1000, [2000], columns=(3000, 3000))


def next_page_break(kind=None):
    stated = f"<w:type w:val='{kind}'/>" if kind else ""
    return (
        f"<w:p><w:pPr><w:sectPr>{stated}<w:pgSz w:w='11906' w:h='16838'/>"
        "<w:pgMar w:left='1440' w:right='1440' w:top='1440' w:bottom='1440'/>"
        "</w:sectPr></w:pPr></w:p>"
    )


def outcome(body):
    root = parse_xml(document(body + A4_SECTION))
    report = transform(root)
    in_table = bool(list(root.find(".//" + q("w", "tbl")).iter(q("wp", "inline"))))
    return report, in_table


def test_a_picture_after_a_next_page_section_break_stays_out_of_the_table():
    """The reproduction on the issue: a table in section one, a picture at
    the same page coordinates in section two."""
    report, in_table = outcome(TABLE + next_page_break() + OVER_THE_TABLE)
    assert not in_table, "the picture was moved into a table on another page"
    assert report["picturesPlaced"] == 0


def test_a_page_break_between_them_keeps_the_picture_out():
    page_break = "<w:p><w:r><w:br w:type='page'/></w:r></w:p>"
    report, in_table = outcome(TABLE + page_break + OVER_THE_TABLE)
    assert not in_table
    assert report["picturesPlaced"] == 0


def test_a_paragraph_starting_a_new_page_keeps_the_picture_out():
    starts_page = "<w:p><w:pPr><w:pageBreakBefore/></w:pPr><w:r><w:t>Next</w:t></w:r></w:p>"
    report, in_table = outcome(TABLE + starts_page + OVER_THE_TABLE)
    assert not in_table
    assert report["picturesPlaced"] == 0


def test_a_continuous_section_break_does_not_start_a_page():
    report, in_table = outcome(TABLE + next_page_break("continuous") + OVER_THE_TABLE)
    assert in_table
    assert report["picturesPlaced"] == 1


def test_far_apart_with_no_record_of_pages_is_reported_not_guessed():
    """In a single long section nothing marks where a page ends, so a picture
    many paragraphs away may well be on another page."""
    filler = NOT_ADJACENT_TO_TABLE * 6
    report, in_table = outcome(OVER_THE_TABLE + filler + TABLE)
    assert not in_table
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1


def test_far_apart_on_a_page_word_recorded_is_placed():
    """Word marks each page it laid out (w:lastRenderedPageBreak). With that
    record and none between them, the two are on one page, however far apart."""
    rendered = "<w:p><w:r><w:lastRenderedPageBreak/><w:t>Page two</w:t></w:r></w:p>"
    filler = NOT_ADJACENT_TO_TABLE * 6
    report, in_table = outcome(OVER_THE_TABLE + filler + TABLE + rendered)
    assert in_table
    assert report["picturesPlaced"] == 1


def test_a_recorded_page_end_between_them_keeps_the_picture_out():
    rendered = "<w:p><w:r><w:lastRenderedPageBreak/><w:t>Page two</w:t></w:r></w:p>"
    report, in_table = outcome(TABLE + rendered + OVER_THE_TABLE)
    assert not in_table
    assert report["picturesPlaced"] == 0


def test_a_page_break_inside_a_run_of_pictures_above_a_table_stops_the_order_pass():
    """The order-based pass reads pictures stacked above a table. One on the
    page before a break is not over this table, whatever its offset says."""
    body = (
        para(floating(200000, 100000))
        + "<w:p><w:pPr><w:pageBreakBefore/></w:pPr></w:p>"
        + para(floating(4000000, 100000))
        + question_table(rows=1)
    )
    root = parse_xml(document(body + A4_SECTION))
    report = transform(root)
    assert report["picturesPlaced"] == 0
    assert report["picturesUnplaced"] == 2


def test_an_uncertain_picture_reaches_the_saved_report(tmp_path):
    """A count that never reaches the report cannot tell anyone to look."""
    filler = NOT_ADJACENT_TO_TABLE * 6
    report, _ = converted_job(tmp_path, OVER_THE_TABLE + filler + TABLE + A4_SECTION)
    assert report["conversion"]["picturesGeometryUncertain"] == 1
