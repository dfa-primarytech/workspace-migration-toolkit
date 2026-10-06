"""Forms built as page-sized text boxes: width, order and containment.

A school form was one text box covering the page, holding a header, two
bordered tables and, in a second small box, a "reviewed" panel near the foot.
Converted, the right-hand column was cut off, the boxes came out in the wrong
order and the foot panel landed pages away from the form. These tests use
synthetic content of the same shape; no real document is involved.
"""

from __future__ import annotations

from workspace_toolkit.docs import transform

from .test_docx import document, local, offset, para, parse_xml, q, run

# A4 with 1-inch margins: 9026 twips of text between the margins.
PAGE = "<w:sectPr><w:pgSz w:w='11906' w:h='16838'/><w:pgMar w:top='1440' w:right='1440' w:bottom='1440' w:left='1440'/></w:sectPr>"
EMU_PER_DXA = 635


def box(content: str, *, fill: bool = False) -> str:
    return (
        '<a:graphic><a:graphicData uri="x"><wps:wsp><wps:spPr>'
        + ("<a:solidFill><a:srgbClr val='FFE599'/></a:solidFill>" if fill else "<a:noFill/>")
        + f"</wps:spPr><wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx></wps:wsp>"
        "</a:graphicData></a:graphic>"
    )


def text(words: str) -> str:
    return f"<w:p><w:r><w:t>{words}</w:t></w:r></w:p>"


def table(words: str, width: int, *, indent: int = 0) -> str:
    return (
        f"<w:tbl><w:tblPr><w:tblW w:w='{width}' w:type='dxa'/>"
        f"<w:tblInd w:w='{indent}' w:type='dxa'/></w:tblPr>"
        f"<w:tblGrid><w:gridCol w:w='{width}'/></w:tblGrid>"
        f"<w:tr><w:tc><w:tcPr><w:tcW w:w='{width}' w:type='dxa'/></w:tcPr>{text(words)}</w:tc></w:tr></w:tbl>"
    )


def wide_box(content: str, *, width: int, left: int, top: int = 390525, height: int = 9000000):
    """A floating box: `left` is its offset from the left margin, in EMU."""
    return run(
        box(content),
        h=("margin", offset(left)),
        v=("page", offset(top)),
        cx=width * EMU_PER_DXA,
        cy=height,
    )


def body_tables(root):
    body = root.find(q("w", "body"))
    return [child for child in body if local(child.tag) == "tbl"]


def words(element) -> str:
    return " ".join(t.text or "" for t in element.iter(q("w", "t")))


def grid_total(tbl) -> int:
    grid = tbl.find(q("w", "tblGrid"))
    return sum(int(c.get(q("w", "w"))) for c in grid)


def stated_width(tbl) -> int:
    return int(tbl.find(q("w", "tblPr") + "/" + q("w", "tblW")).get(q("w", "w")))


# 538 pt wide, 34 pt left of the margin: it ends well inside the 595 pt page.
FORM_WIDTH = 10770
FORM_LEFT = -428625


def test_a_box_that_hangs_into_the_margin_but_fits_the_page_keeps_its_width():
    inner = text("Heading") + table("Results", 10093, indent=250)
    root = parse_xml(
        document(para(wide_box(inner, width=FORM_WIDTH, left=FORM_LEFT)) + PAGE_PARAGRAPH)
    )
    transform(root)

    (outer,) = body_tables(root)
    assert stated_width(outer) == FORM_WIDTH, "narrowed to the margins though the page has room"
    nested = outer.find(".//" + q("w", "tc") + "//" + q("w", "tbl"))
    assert stated_width(nested) == 10093


def test_a_box_wider_than_its_room_is_narrowed_with_what_it_holds():
    # 700 pt wide from the left margin: it cannot fit a 595 pt page.
    inner = text("Heading") + table("Results", 13800)
    root = parse_xml(document(para(wide_box(inner, width=14000, left=0)) + PAGE_PARAGRAPH))
    transform(root)

    (outer,) = body_tables(root)
    room = 11906 - 1440
    assert stated_width(outer) <= room
    nested = outer.find(".//" + q("w", "tc") + "//" + q("w", "tbl"))
    assert grid_total(nested) <= stated_width(outer), "the table inside overflows the box"
    assert stated_width(nested) == grid_total(nested)


def test_two_boxes_in_one_paragraph_keep_the_order_they_were_written_in():
    first = run(
        box(text("FIRST")),
        h=("margin", offset(0)),
        v=("page", offset(1000000)),
        cx=2000000,
        cy=500000,
    )
    second = run(
        box(text("SECOND")),
        h=("margin", offset(0)),
        v=("page", offset(5000000)),
        cx=2000000,
        cy=500000,
    )
    root = parse_xml(document(para(first, second) + PAGE_PARAGRAPH))
    transform(root)

    order = [words(t).strip() for t in body_tables(root)]
    assert order == ["FIRST", "SECOND"], order


PAGE_PARAGRAPH = f"<w:p><w:pPr>{PAGE}</w:pPr></w:p>"
