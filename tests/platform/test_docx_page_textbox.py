"""Forms built as page-sized text boxes: width, order and containment.

A school form was one text box covering the page, holding a header, two
bordered tables and, in a second small box, a "reviewed" panel near the foot.
Converted, the right-hand column was cut off, the boxes came out in the wrong
order and the foot panel landed pages away from the form. These tests use
synthetic content of the same shape; no real document is involved.
"""

from __future__ import annotations

from workspace_toolkit.docs import DEFAULT_WRAP_GAP_DXA, PANEL_TAIL_DXA, transform

from .test_docx import document, local, offset, para, parse_xml, q, run

# A4 with 1-inch margins: 9026 twips of text between the margins.
PAGE = "<w:sectPr><w:pgSz w:w='11906' w:h='16838'/><w:pgMar w:top='1440' w:right='1440' w:bottom='1440' w:left='1440'/></w:sectPr>"
EMU_PER_DXA = 635


def box(content: str, *, fill: bool = False, line: str = "", anchor: str | None = None) -> str:
    """A text box; `line` is the inner XML of its a:ln, `anchor` its bodyPr anchor."""
    outline = f"<a:ln w='28575'>{line}</a:ln>" if line else ""
    body = f"<wps:bodyPr anchor='{anchor}'/>" if anchor else ""
    return (
        '<a:graphic><a:graphicData uri="x"><wps:wsp><wps:spPr>'
        + ("<a:solidFill><a:srgbClr val='FFE599'/></a:solidFill>" if fill else "<a:noFill/>")
        + f"{outline}</wps:spPr><wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>"
        f"{body}</wps:wsp></a:graphicData></a:graphic>"
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


PAGE_PARAGRAPH = f"<w:p><w:pPr>{PAGE}</w:pPr></w:p>"

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


# --- a box inside a page-sized box ---------------------------------------

BLACK = "<a:solidFill><a:srgbClr val='000000'/></a:solidFill>"
PAGE_W_EMU = 11906 * EMU_PER_DXA
PAGE_H_EMU = 16838 * EMU_PER_DXA
MARGIN_EMU = 1440 * EMU_PER_DXA


def form(*, footer_top: int = 8159115, footer_frame: str = "paragraph", footer_first=True):
    """A page-sized box and a small panel in it, anchored in one paragraph."""
    big = run(
        box(text("Header") + table("Results", 10093, indent=250) + text("Plan"), line=BLACK),
        h=("margin", offset(-428625)),
        v=("page", offset(390525)),
        cx=6829425,
        cy=10001250,
    )
    small = run(
        box(text("Reviewed by") + text("Done"), line=BLACK),
        h=("column", offset(-150495)),
        v=(footer_frame, offset(footer_top)),
        cx=6229350,
        cy=1066800,
    )
    runs = (small, big) if footer_first else (big, small)
    return document(para(*runs) + PAGE_PARAGRAPH)


def test_a_panel_inside_a_page_sized_box_goes_inside_its_table():
    root = parse_xml(form())
    report = transform(root)

    (outer,) = body_tables(root)
    assert report["textboxes"] == 2
    flat = words(outer)
    assert flat.index("Header") < flat.index("Plan") < flat.index("Reviewed by"), flat


def test_the_panel_keeps_its_height_down_the_page_so_it_stays_at_the_foot():
    root = parse_xml(form())
    transform(root)

    (outer,) = body_tables(root)
    rows = outer.findall(q("w", "tr"))
    assert len(rows) == 2
    height = rows[0].find(q("w", "trPr") + "/" + q("w", "trHeight"))
    assert height.get(q("w", "hRule")) == "atLeast"
    # The panel would end below the bottom margin, so it is lifted to end at
    # it: from the box's top to (page - bottom margin - panel).
    expected = (
        (PAGE_H_EMU - MARGIN_EMU - 1066800 - 390525) // EMU_PER_DXA
        - PANEL_TAIL_DXA
        - DEFAULT_WRAP_GAP_DXA
    )
    assert abs(int(height.get(q("w", "val"))) - expected) <= 2


def test_the_same_form_comes_out_the_same_whichever_box_was_written_first():
    first, second = parse_xml(form(footer_first=True)), parse_xml(form(footer_first=False))
    transform(first)
    transform(second)

    assert words(body_tables(first)[0]) == words(body_tables(second)[0])


def test_a_panel_that_lies_outside_the_big_box_is_left_alone():
    # Below the big box's bottom edge: nothing says it belongs inside.
    root = parse_xml(form(footer_top=9500000, footer_frame="page"))
    transform(root)

    assert len(body_tables(root)) == 2


def test_a_box_keeps_its_outline():
    line = "<a:solidFill><a:srgbClr val='1F3864'/></a:solidFill>"
    one = run(box(text("Framed"), line=line), h=("margin", offset(0)), v=("page", offset(0)))
    root = parse_xml(document(para(one) + PAGE_PARAGRAPH))
    transform(root)

    (framed,) = body_tables(root)
    top = framed.find(q("w", "tblPr") + "/" + q("w", "tblBorders") + "/" + q("w", "top"))
    assert top.get(q("w", "val")) == "single"
    assert top.get(q("w", "color")).upper() == "1F3864"
    assert top.get(q("w", "sz")) == "18", "2.25 pt is 18 eighths"


def test_a_box_with_no_outline_stays_unframed():
    one = run(box(text("Plain")), h=("margin", offset(0)), v=("page", offset(0)))
    root = parse_xml(document(para(one) + PAGE_PARAGRAPH))
    transform(root)

    (plain,) = body_tables(root)
    top = plain.find(q("w", "tblPr") + "/" + q("w", "tblBorders") + "/" + q("w", "top"))
    assert top.get(q("w", "val")) == "none"


def test_a_box_that_says_its_text_starts_at_the_top_is_aligned_to_the_top():
    one = run(box(text("Top"), anchor="t"), h=("margin", offset(0)), v=("page", offset(0)))
    root = parse_xml(document(para(one) + PAGE_PARAGRAPH))
    transform(root)

    (top,) = body_tables(root)
    align = top.find(".//" + q("w", "vAlign"))
    assert align.get(q("w", "val")) == "top"
