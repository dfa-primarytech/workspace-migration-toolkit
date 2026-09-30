"""Placement measured against the right page: #112, #115, #116, #117, #118, #135.

Every pass that sizes or places content measures it against a page. Each of
these read the wrong one: the final section's for every table (#135), a
tracked change's old margins (#115), the text area for every margin frame
(#112), a row's n-th cell for its n-th grid column (#117). Two more changed
what was already right: a text box's own spacing (#116), and a group's
children scaled twice when its column narrowed (#118).
"""

from __future__ import annotations

from workspace_toolkit.docs import transform

from .test_docx import (
    A4_SECTION,
    NOT_ADJACENT_TO_TABLE,
    PICTURE,
    TEXTBOX,
    anchor,
    document,
    floating,
    in_cell,
    local,
    offset,
    para,
    parse_body,
    parse_xml,
    q,
    question_table,
    wide_table,
    widths,
)

MARGINS = "<w:pgMar w:left='1440' w:right='1440' w:top='1440' w:bottom='1440'/>"
PORTRAIT = f"<w:pgSz w:w='11906' w:h='16838'/>{MARGINS}"
LANDSCAPE = f"<w:pgSz w:w='16838' w:h='11906' w:orient='landscape'/>{MARGINS}"


def ends_section(properties):
    return f"<w:p><w:pPr><w:sectPr>{properties}</w:sectPr></w:pPr></w:p>"


# ------------------------------------------------ #135: each table's own page


def test_a_landscape_table_before_a_portrait_section_is_left_as_it_was():
    """12000 twips fits the landscape page's 13958; only the final, portrait
    section is 9026 wide, and that is not this table's page."""
    body = wide_table() + ends_section(LANDSCAPE) + f"<w:sectPr>{PORTRAIT}</w:sectPr>"
    root = parse_xml(document(body))
    report = transform(root)

    assert report["tablesNarrowed"] == 0
    assert widths(root) == [6000, 6000]


def test_a_portrait_table_before_a_landscape_section_is_narrowed_to_its_page():
    body = wide_table() + ends_section(PORTRAIT) + f"<w:sectPr>{LANDSCAPE}</w:sectPr>"
    root = parse_xml(document(body))
    report = transform(root)

    assert report["tablesNarrowed"] == 1
    assert sum(widths(root)) <= 9026


# ------------------------------------ #115: current margins, not tracked ones


def test_a_picture_is_measured_from_the_current_margin_not_a_tracked_one():
    """Current left margin 720 twips, 1440 before a tracked change. Measured
    from the old one, a picture just inside the right column lands in the left."""
    tracked = (
        "<w:sectPr><w:pgSz w:w='11906' w:h='16838'/>"
        "<w:pgMar w:left='720' w:right='720' w:top='1440' w:bottom='1440'/>"
        "<w:sectPrChange w:id='1' w:author='a'><w:sectPr>"
        "<w:pgMar w:left='1440' w:right='1440' w:top='1440' w:bottom='1440'/>"
        "</w:sectPr></w:sectPrChange></w:sectPr>"
    )
    margin = 720 * 635
    body = para(floating(margin + 3700000, 100000, cx=200000, frame_h="page"))
    root = parse_xml(document(body + question_table(rows=1) + tracked))
    report = transform(root)

    assert report["picturesPlaced"] == 1
    per_cell = [len(list(tc.iter(q("wp", "inline")))) for tc in root.iter(q("w", "tc"))]
    assert per_cell == [0, 0, 0, 1], per_cell


# --------------------------------------- #117: grid columns, not cell indexes


def positioned(rows, columns=(3000, 3000, 3000)):
    """A table pinned to page (1000, 1000) twips, one exact 2000-twip row per
    entry in `rows`, each the row's own inner XML."""
    grid = "".join(f"<w:gridCol w:w='{w}'/>" for w in columns)
    body = "".join(
        f"<w:tr><w:trPr>{extra}<w:trHeight w:val='2000' w:hRule='exact'/></w:trPr>{cells}</w:tr>"
        for extra, cells in rows
    )
    return (
        "<w:tbl><w:tblPr><w:tblpPr w:horzAnchor='page' w:vertAnchor='page' "
        f"w:tblpX='1000' w:tblpY='1000'/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>"
    )


def cell(label, span=1, merge=""):
    properties = f"<w:gridSpan w:val='{span}'/>" if span > 1 else ""
    properties += merge
    return f"<w:tc><w:tcPr>{properties}</w:tcPr><w:p><w:r><w:t>{label}</w:t></w:r></w:p></w:tc>"


def over_column(column, row=0):
    """A small picture well inside grid column `column` of row `row`."""
    x = (1000 + column * 3000 + 500) * 635
    y = (1000 + row * 2000 + 500) * 635
    picture = anchor(PICTURE, h=("page", offset(x)), v=("page", offset(y)), cx=300000, cy=300000)
    return picture + NOT_ADJACENT_TO_TABLE


def pictures_by_cell(body):
    root = parse_xml(document(body + A4_SECTION))
    report = transform(root)
    found = {
        "".join(t.text or "" for t in tc.iter(q("w", "t"))): len(list(tc.iter(q("wp", "inline"))))
        for tc in root.iter(q("w", "tc"))
    }
    return report, found


def test_a_picture_over_a_merged_cell_goes_into_that_cell():
    """Grid column 1 is inside the first cell, which spans columns 0 and 1."""
    table = positioned([("", cell("A", span=2) + cell("B"))])
    report, found = pictures_by_cell(over_column(1) + table)
    assert report["picturesPlaced"] == 1
    assert found == {"A": 1, "B": 0}, found


def test_a_picture_is_placed_past_the_columns_a_row_skips():
    """w:gridBefore leaves grid column 0 with no cell: B covers column 1."""
    table = positioned([("<w:gridBefore w:val='1'/>", cell("B") + cell("C"))])
    report, found = pictures_by_cell(over_column(1) + table)
    assert report["picturesPlaced"] == 1
    assert found == {"B": 1, "C": 0}, found


def test_a_picture_over_the_lower_part_of_a_vertical_merge_is_reported():
    """That part shows the upper cell's content, not its own; putting the
    picture in it would hide it."""
    table = positioned(
        [
            ("", cell("Top", merge="<w:vMerge w:val='restart'/>") + cell("R1") + cell("S1")),
            ("", cell("Low", merge="<w:vMerge/>") + cell("R2") + cell("S2")),
        ]
    )
    report, found = pictures_by_cell(over_column(0, row=1) + table)
    assert report["picturesPlaced"] == 0
    assert report["picturesGeometryUncertain"] == 1
    assert sum(found.values()) == 0


def test_the_order_pass_also_follows_the_grid():
    """The same indexing in the pass for pictures stacked above a table."""
    grid = "".join(f"<w:gridCol w:w='{w}'/>" for w in (3000, 3000, 3000))
    table = (
        f"<w:tbl><w:tblPr/><w:tblGrid>{grid}</w:tblGrid>"
        f"<w:tr>{cell('1.', span=2)}{cell('2.')}</w:tr></w:tbl>"
    )
    # Over grid column 2, the third column: the second cell, not a third.
    body = para(floating(4200000, 100000, cx=500000)) + table
    report, found = pictures_by_cell(body)
    assert report["picturesPlaced"] == 1
    assert found == {"1.": 0, "2.": 1}, found


# ------------------------------------------------ #112: margin frames


def textbox_position(tmp_path, frame, value):
    body = anchor(TEXTBOX, h=(frame, offset(value)), v=("page", offset(0))) + A4_SECTION
    root = parse_xml(document(body))
    report = transform(root)
    position = root.find(".//" + q("w", "tblpPr"))
    manifest = parse_body(tmp_path, body)
    return position, report, manifest["pages"][0]["elements"][0]


def test_a_right_margin_note_stays_in_the_right_margin(tmp_path):
    """Offset 0 from the right margin is where the text area ends, not where
    it starts: 11906 - 1440 twips from the paper's left edge."""
    position, _, element = textbox_position(tmp_path, "rightMargin", 0)
    assert position.get(q("w", "horzAnchor")) == "page"
    assert position.get(q("w", "tblpX")) == str(11906 - 1440)
    assert element["bounds"]["x"] == (11906 - 1440) / 20


def test_a_left_margin_offset_counts_from_the_paper_edge(tmp_path):
    position, _, _ = textbox_position(tmp_path, "leftMargin", 1828800)
    assert position.get(q("w", "horzAnchor")) == "page"
    assert position.get(q("w", "tblpX")) == "2880", "2in from the paper, not 3in"


def test_a_bottom_margin_offset_counts_from_where_the_text_ends():
    body = anchor(TEXTBOX, h=("page", offset(0)), v=("bottomMargin", offset(127000))) + A4_SECTION
    root = parse_xml(document(body))
    transform(root)
    position = root.find(".//" + q("w", "tblpPr"))
    assert position.get(q("w", "vertAnchor")) == "page"
    assert position.get(q("w", "tblpY")) == str(16838 - 1440 + 200)


def test_an_inside_margin_position_is_kept_and_reported_as_uncertain(tmp_path):
    """Which side the inside margin is on depends on the page, which is not
    known here. The box goes where it always went, and the report says so."""
    position, report, element = textbox_position(tmp_path, "insideMargin", 457200)
    assert report["textboxes"] == 1, "the text box is still converted"
    assert position.get(q("w", "horzAnchor")) == "margin"
    assert position.get(q("w", "tblpX")) == "720"
    assert report["positionsPageSideUncertain"] == 1
    codes = [w["code"] for w in element["warnings"]]
    assert codes == ["position_page_side_uncertain"], codes


def test_a_left_margin_picture_is_placed_by_the_paper_edge():
    """The geometry pass: 2in from the paper puts a picture in the table's
    first cell. Read as 2in past the 1in margin, it missed the table."""
    table = positioned([("", cell("A") + cell("B") + cell("C"))])
    x = (1000 + 500) * 635
    y = (1000 + 500) * 635
    picture = anchor(
        PICTURE, h=("leftMargin", offset(x)), v=("topMargin", offset(y)), cx=300000, cy=300000
    )
    report, found = pictures_by_cell(picture + NOT_ADJACENT_TO_TABLE + table)
    assert report["picturesPlaced"] == 1
    assert found == {"A": 1, "B": 0, "C": 0}, found


# ------------------------------------------ #116: a text box's own spacing


def inline_picture_paragraph():
    return (
        '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="900000" cy="900000"/>'
        f"<wp:docPr/>{PICTURE}</wp:inline></w:drawing></w:r></w:p>"
    )


def test_a_text_box_holding_a_picture_keeps_its_blank_lines():
    """A logo, two spacer lines, then an address: the cell the box becomes is
    new, but its picture was always there, so nothing was holding its place."""
    content = (
        inline_picture_paragraph() + "<w:p/><w:p/>" + "<w:p><w:r><w:t>Address</w:t></w:r></w:p>"
    )
    box = (
        '<a:graphic><a:graphicData uri="x"><wps:wsp><wps:spPr/>'
        f"<wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )
    body = anchor(box, h=("column", offset(0)), v=("paragraph", offset(0))) + A4_SECTION
    root = parse_xml(document(body))
    report = transform(root)

    assert report["textboxes"] == 1
    assert report["blankLinesReclaimed"] == 0
    cell_paragraphs = root.find(".//" + q("w", "tc")).findall(q("w", "p"))
    assert len(cell_paragraphs) == 4, "picture, two blank lines, address"


def test_a_cell_that_gains_a_picture_still_has_its_placeholder_lines_reclaimed():
    """#116 must not undo the reclaim it sits beside."""
    body = in_cell("<w:p/><w:p/>" + anchor(PICTURE)) + A4_SECTION
    root = parse_xml(document(body))
    report = transform(root)
    assert report["blankLinesReclaimed"] == 2


# ------------------------------------------- #118: a group scales as a whole

GROUP_URI = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"


def grouped_shapes():
    """A 3810000-wide group holding two children in its own 1000-unit space."""
    child = (
        "<wps:wsp><wps:spPr><a:xfrm><a:off x='{x}' y='0'/><a:ext cx='200' cy='200'/>"
        "</a:xfrm></wps:spPr></wps:wsp>"
    )
    return (
        "<w:p><w:r><w:drawing><wp:inline>"
        "<wp:extent cx='3810000' cy='1905000'/><wp:docPr/>"
        f'<a:graphic><a:graphicData uri="{GROUP_URI}"><wpg:wgp xmlns:wpg="{GROUP_URI}">'
        "<wpg:grpSpPr><a:xfrm>"
        "<a:off x='0' y='0'/><a:ext cx='3810000' cy='1905000'/>"
        "<a:chOff x='0' y='0'/><a:chExt cx='1000' cy='500'/></a:xfrm></wpg:grpSpPr>"
        + child.format(x=0)
        + child.format(x=800)
        + "</wpg:wgp></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )


def test_a_group_in_a_narrowed_column_shrinks_once():
    """A child is drawn at its a:ext times the group's a:ext over a:chExt.
    Scaling the group's size already scales the children; scaling their a:ext
    as well shrank them twice while their offsets moved once."""
    root = parse_xml(document(wide_table(grouped_shapes()) + A4_SECTION))
    report = transform(root)
    assert report["picturesShrunk"] == 1

    group = root.find(".//{" + GROUP_URI + "}grpSpPr/" + q("a", "xfrm"))
    outer = root.find(".//" + q("wp", "extent"))
    assert group.find(q("a", "ext")).get("cx") == outer.get("cx"), "frame and group agree"
    assert int(outer.get("cx")) < 3810000
    assert group.find(q("a", "chExt")).get("cx") == "1000", "the group's own space is kept"
    children = [
        (int(xfrm.find(q("a", "off")).get("x")), int(xfrm.find(q("a", "ext")).get("cx")))
        for xfrm in root.iter(q("a", "xfrm"))
        if local(xfrm.tag) == "xfrm" and xfrm.find(q("a", "chExt")) is None
    ]
    assert children == [(0, 200), (800, 200)], "children keep their place in the group"
