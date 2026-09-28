"""Right-to-left documents: what survives, and what we had to state ourselves.

A trust teaching Arabic, Urdu or Hebrew holds documents where direction is not
decoration -- lose it and the text renders in the wrong order, which is not a
formatting blemish but a different sentence.

Most of this turned out to be already safe, and the reason is worth recording:
the converter *relocates* paragraphs into a table cell rather than rebuilding
them, so `w:bidi`, `w:rtl`, `w:jc` and `w:lang` travel with the elements that
carry them. These tests pin that, because "it works because of how the code
happens to be written" becomes "it worked until someone rewrote it".

The genuine gaps were the parts the converter *creates*, which have no author
to inherit direction from: the table itself, the filler paragraph an empty
cell requires, and the separators that keep two tables from merging.

What is deliberately *not* claimed here is effective direction resolution. The
converter reads `w:bidi` where an author wrote it on the paragraph, and that is
all. It does not resolve direction inherited from a paragraph style, and a box
whose paragraphs disagree with each other gets the first stated direction,
because there is one table to put one direction on.
"""

from __future__ import annotations

import pytest

from .test_docx import (
    TEXTBOX,
    anchor,
    offset,
    q,
    transform_body,
)
from .test_docx_sections import A4_PORTRAIT, box, final_section, section_break_with, table

# Deliberately not a transliteration: the point is that the bytes survive.
ARABIC = "مرحبا بالعالم"
HEBREW = "שלום עולם"

RTL_PROPERTIES = "<w:pPr><w:bidi/><w:jc w:val='right'/></w:pPr>"
RTL_RUN_PROPERTIES = "<w:rPr><w:rtl/><w:lang w:bidi='ar-SA'/></w:rPr>"


def rtl_paragraph(content: str = ARABIC) -> str:
    return (
        f"<w:p>{RTL_PROPERTIES}"
        f"<w:r>{RTL_RUN_PROPERTIES}<w:t xml:space='preserve'>{content}</w:t></w:r>"
        "</w:p>"
    )


def rtl_box(content: str = ARABIC) -> str:
    """A text box whose paragraphs read right to left."""
    return TEXTBOX.replace("<w:p><w:r><w:t>Card text</w:t></w:r></w:p>", rtl_paragraph(content))


def rtl_anchor(content: str = ARABIC) -> str:
    return anchor(rtl_box(content), h=("column", offset(0)), v=("paragraph", offset(0)))


# ------------------------------------------------------- what already survived


def test_direction_travels_with_the_paragraph_into_the_cell(tmp_path):
    """The move into a table cell is where markup gets lost if anything rebuilds."""
    root, report = transform_body(tmp_path, rtl_anchor() + final_section())
    assert report["textboxes"] == 1

    cell = root.find(".//" + q("w", "tc"))
    assert cell is not None
    for tag in ("bidi", "jc", "rtl", "lang"):
        assert cell.find(".//" + q("w", tag)) is not None, (
            f"w:{tag} did not survive the move into the table cell; the text "
            "will render in the wrong direction"
        )


@pytest.mark.parametrize("content", [ARABIC, HEBREW], ids=["arabic", "hebrew"])
def test_the_text_itself_is_unchanged(tmp_path, content):
    """Direction markup is worthless if the characters were mangled on the way."""
    root, _ = transform_body(tmp_path, rtl_anchor(content) + final_section())
    cell = root.find(".//" + q("w", "tc"))
    assert cell is not None
    recovered = "".join(t.text or "" for t in cell.iter(q("w", "t")))
    assert recovered == content, f"expected {content!r}, got {recovered!r}"


def test_a_right_to_left_body_paragraph_is_left_alone(tmp_path):
    """Nothing outside a text box should be touched at all."""
    body = rtl_paragraph() + rtl_anchor() + final_section()
    root, _ = transform_body(tmp_path, body)
    paragraphs = [
        p
        for p in root.find(q("w", "body"))
        if p.tag.endswith("}p") and p.find(f"{q('w', 'pPr')}/{q('w', 'bidi')}") is not None
    ]
    assert paragraphs, "the body's own right-to-left paragraph lost its direction"


def test_a_section_reading_right_to_left_keeps_saying_so(tmp_path):
    """sectPr carries w:bidi as the section default; dropping it flips the page."""
    body = rtl_anchor() + f"<w:sectPr><w:bidi/><w:pgSz {A4_PORTRAIT}/></w:sectPr>"
    root, _ = transform_body(tmp_path, body)
    section = root.find(".//" + q("w", "sectPr"))
    assert section is not None
    assert section.find(q("w", "bidi")) is not None, "the section's direction was dropped"


# ------------------------------------------------- what the converter creates


def test_the_converted_table_states_its_direction(tmp_path):
    root, _ = transform_body(tmp_path, rtl_anchor() + final_section())
    properties = root.find(".//" + q("w", "tbl") + "/" + q("w", "tblPr"))
    assert properties is not None
    assert properties.find(q("w", "bidiVisual")) is not None, (
        "a right-to-left text box became a table that does not say it reads right to left"
    )


def test_bidi_visual_sits_where_the_schema_requires(tmp_path):
    """CT_TblPrBase order: tblpPr, tblOverlap, bidiVisual, then tblW.

    Every element is individually valid whatever the order, so no assertion
    about the *presence* of any of them would catch this -- it has to be
    checked as an order, which is what this does.

    The LibreOffice case cannot stand in for it. A tolerant reader opening the
    file proves interoperability with that reader, not conformance; only a
    validating parser would reject bad order outright, and we do not run one.
    """
    root, _ = transform_body(tmp_path, rtl_anchor() + final_section())
    properties = root.find(".//" + q("w", "tbl") + "/" + q("w", "tblPr"))
    order = [child.tag.rsplit("}", 1)[-1] for child in properties]
    assert "bidiVisual" in order, order
    assert order.index("bidiVisual") < order.index("tblW"), (
        f"bidiVisual must precede tblW in CT_TblPrBase. order={order}"
    )
    if "tblOverlap" in order:
        assert order.index("tblOverlap") < order.index("bidiVisual"), (
            f"tblOverlap must precede bidiVisual. order={order}"
        )


def test_a_left_to_right_box_gains_nothing(tmp_path):
    """The marker must mean something: an ordinary document stays unchanged."""
    body = anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0)))
    root, _ = transform_body(tmp_path, body + final_section())
    properties = root.find(".//" + q("w", "tbl") + "/" + q("w", "tblPr"))
    assert properties.find(q("w", "bidiVisual")) is None, (
        "a left-to-right text box was marked right-to-left"
    )


@pytest.mark.parametrize("off", ["0", "false", "off"], ids=["zero", "false", "off"])
def test_a_box_that_turns_direction_off_beats_a_right_to_left_anchor(tmp_path, off):
    """An explicit `w:val="0"` is an instruction, not an absence.

    `ST_OnOff` spells false three ways and all three mean the same thing. A
    box that says "read me left to right" sitting inside a right-to-left
    document is the whole reason the box is consulted before its anchor; if an
    explicit override loses to the surrounding text there was no point reading
    the box at all.
    """
    ltr_box = TEXTBOX.replace(
        "<w:p><w:r><w:t>Card text</w:t></w:r></w:p>",
        f"<w:p><w:pPr><w:bidi w:val='{off}'/></w:pPr><w:r><w:t>Latin text</w:t></w:r></w:p>",
    )
    body = (
        f"<w:p>{RTL_PROPERTIES}"
        + anchor(ltr_box, h=("column", offset(0)), v=("paragraph", offset(0)))[len("<w:p>") :]
        + final_section()
    )
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 1

    properties = root.find(".//" + q("w", "tbl") + "/" + q("w", "tblPr"))
    assert properties.find(q("w", "bidiVisual")) is None, (
        f"w:bidi w:val='{off}' turns direction off, but the box was still "
        "made right-to-left by its anchor"
    )


def test_a_right_to_left_box_beats_a_left_to_right_anchor(tmp_path):
    """The opposing case, so the rule is not satisfied by always saying no."""
    body = (
        "<w:p><w:pPr><w:bidi w:val='0'/></w:pPr>"
        + anchor(rtl_box(), h=("column", offset(0)), v=("paragraph", offset(0)))[len("<w:p>") :]
        + final_section()
    )
    root, _ = transform_body(tmp_path, body)
    properties = root.find(".//" + q("w", "tbl") + "/" + q("w", "tblPr"))
    assert properties.find(q("w", "bidiVisual")) is not None, (
        "the box's own right-to-left paragraphs were overruled by its anchor"
    )


def test_a_box_that_says_nothing_follows_its_anchor(tmp_path):
    """Absence is the only case where the anchor gets a say."""
    silent = TEXTBOX  # "Card text" with no pPr at all
    body = (
        f"<w:p>{RTL_PROPERTIES}"
        + anchor(silent, h=("column", offset(0)), v=("paragraph", offset(0)))[len("<w:p>") :]
        + final_section()
    )
    root, _ = transform_body(tmp_path, body)
    properties = root.find(".//" + q("w", "tbl") + "/" + q("w", "tblPr"))
    assert properties.find(q("w", "bidiVisual")) is not None, (
        "a box stating no direction should follow the paragraph it is anchored to"
    )


def test_an_empty_box_is_not_converted_at_all(tmp_path):
    """Nothing to make editable, so nothing to build.

    This used to check that the filler paragraph of an empty box's cell took
    its direction from the anchor. That case cannot arise now: a real
    worksheet turned out to carry four empty boxes of a quarter-inch square,
    left behind by editing, and converting them produced four floating tables
    holding nothing. An empty box is skipped, so there is no cell and no
    filler to give a direction to.
    """
    empty = TEXTBOX.replace("<w:p><w:r><w:t>Card text</w:t></w:r></w:p>", "")
    body = (
        f"<w:p>{RTL_PROPERTIES}"
        + anchor(empty, h=("column", offset(0)), v=("paragraph", offset(0)))[len("<w:p>") :]
        + final_section()
    )
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 0, "an empty box was reported as converted"
    assert root.find(".//" + q("w", "tbl")) is None, "an empty box produced a table"


def test_a_table_separator_reads_the_same_way_as_its_neighbours(tmp_path):
    """The separator that stops two tables merging is also one we create."""
    body = (
        table("جدول")
        + section_break_with(box(), size=A4_PORTRAIT).replace(
            "<w:pPr><w:sectPr>", "<w:pPr><w:bidi/><w:sectPr>"
        )
        + final_section()
    )
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 1

    children = list(root.find(q("w", "body")))
    names = [c.tag.rsplit("}", 1)[-1] for c in children]
    assert names.count("tbl") == 2, f"expected both tables: {names}"

    separators = [
        c
        for c, name in zip(children, names, strict=True)
        if name == "p" and not list(c.iter(q("w", "r"))) and c.find(q("w", "pPr")) is not None
    ]
    assert separators, f"no separator paragraph was inserted: {names}"
    assert any(p.find(f"{q('w', 'pPr')}/{q('w', 'bidi')}") is not None for p in separators), (
        "the inserted separator reads left to right inside a right-to-left document"
    )
