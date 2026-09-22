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

    Every element here is individually valid, so nothing in our own suite
    would notice this being wrong -- only a validating reader would, by which
    point a member of staff is looking at an error instead of their document.
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


def test_an_empty_box_takes_its_direction_from_where_it_is_anchored(tmp_path):
    """OOXML requires a paragraph in every cell, so we supply one.

    It is ours, not the author's, so nothing gives it a direction -- and an
    empty text box carries no paragraph to read one from either. The anchoring
    paragraph is then the only evidence available. Left bare in a
    right-to-left document the cell reads left to right, putting the paragraph
    mark and the caret on the wrong side.
    """
    empty = TEXTBOX.replace("<w:p><w:r><w:t>Card text</w:t></w:r></w:p>", "")
    body = (
        f"<w:p>{RTL_PROPERTIES}"
        + anchor(empty, h=("column", offset(0)), v=("paragraph", offset(0)))[len("<w:p>") :]
        + final_section()
    )
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 1

    cell = root.find(".//" + q("w", "tc"))
    paragraphs = cell.findall(q("w", "p"))
    assert paragraphs, "the cell has no paragraph at all, which is invalid"
    assert any(p.find(f"{q('w', 'pPr')}/{q('w', 'bidi')}") is not None for p in paragraphs), (
        "the cell's own filler paragraph reads left to right inside a right-to-left document"
    )


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
