"""Multi-section documents, and the section shape real files actually use.

Word places section properties in two different spots, and the distinction has
not been exercised until now:

* every section **except the last** ends with a paragraph whose `pPr` carries
  the `sectPr`
* the **last** section's `sectPr` is a direct child of `<w:body>`

The existing fixtures all use the paragraph form. Checked against the four real
worksheets this converter was built on: every one has a body-level `sectPr` and
**zero** paragraph-level ones. So the suite has been testing the non-final
shape exclusively, and the shape every real document uses not at all.

A letter with a landscape appendix, or a policy whose cover page has different
margins, is an ordinary thing for a trust to hold. These tests cover both
forms, per-section page setup, and where converted content lands relative to a
section boundary.
"""

from __future__ import annotations

import pytest

from .test_docx import (
    TEXTBOX,
    anchor,
    offset,
    parse_body,
    q,
    transform_body,
)

A4_PORTRAIT = 'w:w="11906" w:h="16838"'
A4_LANDSCAPE = 'w:w="16838" w:h="11906"'
A5_PORTRAIT = 'w:w="8419" w:h="11906"'


def final_section(size: str = A4_PORTRAIT, extra: str = "") -> str:
    """The last section: sectPr sits directly in the body.

    This is the shape every real document examined uses, and the one the
    fixtures never had.
    """
    return f"<w:sectPr><w:pgSz {size}/>{extra}</w:sectPr>"


def section_break(size: str = A4_PORTRAIT, extra: str = "") -> str:
    """A non-final section: sectPr rides inside the closing paragraph's pPr."""
    return f"<w:p><w:pPr><w:sectPr><w:pgSz {size}/>{extra}</w:sectPr></w:pPr></w:p>"


def text(content: str) -> str:
    return f"<w:p><w:r><w:t>{content}</w:t></w:r></w:p>"


# ---------------------------------------------------------------- parsing


def test_the_body_level_section_is_read_at_all(tmp_path):
    """The shape every real document uses, and no fixture previously covered."""
    manifest = parse_body(tmp_path, text("Only section") + final_section(A5_PORTRAIT))
    assert manifest["document"]["pageCount"] == 1
    page = manifest["pages"][0]
    assert page["widthPt"] == pytest.approx(420.95, abs=0.01)
    assert page["heightPt"] == pytest.approx(595.3, abs=0.01)


def test_each_section_reports_its_own_page_setup(tmp_path):
    """A landscape appendix after a portrait body is an ordinary document."""
    body = (
        text("Portrait body")
        + section_break(A4_PORTRAIT)
        + text("Landscape appendix")
        + final_section(A4_LANDSCAPE)
    )
    manifest = parse_body(tmp_path, body)
    assert manifest["document"]["pageCount"] == 2
    first, second = manifest["pages"]
    assert first["widthPt"] < first["heightPt"], "first section should be portrait"
    assert second["widthPt"] > second["heightPt"], "second section should be landscape"
    assert second["widthPt"] == pytest.approx(841.9, abs=0.01)


def test_three_sections_of_differing_size_are_all_distinct(tmp_path):
    body = (
        text("A4 portrait")
        + section_break(A4_PORTRAIT)
        + text("A4 landscape")
        + section_break(A4_LANDSCAPE)
        + text("A5 portrait")
        + final_section(A5_PORTRAIT)
    )
    manifest = parse_body(tmp_path, body)
    assert manifest["document"]["pageCount"] == 3
    widths = [round(p["widthPt"]) for p in manifest["pages"]]
    assert widths == [595, 842, 421], f"per-section widths wrong: {widths}"


def test_anchors_land_in_the_section_they_belong_to(tmp_path):
    body = (
        anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0)))
        + section_break(A4_PORTRAIT)
        + anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0)))
        + anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0)))
        + final_section(A4_LANDSCAPE)
    )
    manifest = parse_body(tmp_path, body)
    assert [len(p["elements"]) for p in manifest["pages"]] == [1, 2]


def test_an_anchor_on_the_section_break_paragraph_belongs_to_that_section(tmp_path):
    """A sectPr *ends* its section, so content on that paragraph is still inside it."""
    body = (
        "<w:p><w:pPr><w:sectPr><w:pgSz "
        + A4_PORTRAIT
        + "/></w:sectPr></w:pPr>"
        + "<w:r><w:drawing><wp:anchor><wp:positionH relativeFrom='column'>"
        + offset(0)
        + "</wp:positionH><wp:positionV relativeFrom='paragraph'>"
        + offset(0)
        + "</wp:positionV><wp:extent cx='100' cy='100'/>"
        + TEXTBOX
        + "<wp:docPr/></wp:anchor></w:drawing></w:r></w:p>"
        + text("Second section")
        + final_section(A4_LANDSCAPE)
    )
    manifest = parse_body(tmp_path, body)
    assert [len(p["elements"]) for p in manifest["pages"]] == [1, 0]


def test_page_setup_falls_back_rather_than_crashing(tmp_path):
    """A section with no pgSz at all must not take the whole parse down."""
    manifest = parse_body(tmp_path, text("No page size") + "<w:sectPr/>")
    assert manifest["document"]["pageCount"] == 1
    assert manifest["pages"][0]["widthPt"] == pytest.approx(595.3, abs=0.01)


# ---------------------------------------------------------------- rendering


def test_both_section_forms_survive_the_transform(tmp_path):
    """Losing either loses page size, margins and orientation for that section."""
    body = text("First") + section_break(A4_PORTRAIT) + text("Second") + final_section(A4_LANDSCAPE)
    root, _ = transform_body(tmp_path, body)
    sections = root.findall(".//" + q("w", "sectPr"))
    assert len(sections) == 2, f"expected 2 sectPr after transform, found {len(sections)}"

    sizes = [s.find(q("w", "pgSz")).get(q("w", "w")) for s in sections]
    assert sizes == ["11906", "16838"], "section order or page setup changed"


def test_a_body_level_section_is_not_swallowed_by_the_empty_paragraph_pass(tmp_path):
    """The body-level sectPr has no paragraph protecting it.

    The pass guards paragraphs *carrying* a sectPr. A body-level one is a
    sibling of the paragraphs, so that guard never applies to it -- worth
    pinning, since it is the form every real document uses.
    """
    body = anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0)))
    root, _ = transform_body(tmp_path, body + final_section(A4_LANDSCAPE))
    section = root.find(".//" + q("w", "sectPr"))
    assert section is not None, "the document's only page setup was removed"
    assert section.find(q("w", "pgSz")).get(q("w", "w")) == "16838"


def test_headers_referenced_per_section_are_all_kept(tmp_path):
    """Sections can reference different headers; none should be dropped."""
    body = (
        text("First")
        + section_break(
            A4_PORTRAIT,
            extra="<w:headerReference w:type='default' r:id='rId10'/>",
        )
        + text("Second")
        + final_section(
            A4_LANDSCAPE,
            extra="<w:headerReference w:type='default' r:id='rId11'/><w:titlePg/>",
        )
    )
    root, _ = transform_body(tmp_path, body)
    refs = [r.get(q("r", "id")) for r in root.findall(".//" + q("w", "headerReference"))]
    assert refs == ["rId10", "rId11"], f"header references changed: {refs}"
    assert root.find(".//" + q("w", "titlePg")) is not None


def test_a_converted_text_box_stays_within_its_own_section(tmp_path):
    """Where the table lands decides which page setup it is laid out under.

    The renderer inserts the table after the anchoring paragraph. When that
    paragraph is the one carrying the section break, "after" is the next
    section -- a different page size and orientation.
    """
    body = (
        "<w:p>"
        + "<w:pPr><w:sectPr><w:pgSz "
        + A4_PORTRAIT
        + "/></w:sectPr></w:pPr>"
        + "<w:r><w:drawing><wp:anchor><wp:positionH relativeFrom='column'>"
        + offset(0)
        + "</wp:positionH><wp:positionV relativeFrom='paragraph'>"
        + offset(0)
        + "</wp:positionV><wp:extent cx='2000000' cy='1000000'/>"
        + TEXTBOX
        + "<wp:docPr/></wp:anchor></w:drawing></w:r></w:p>"
        + text("Second section body")
        + final_section(A4_LANDSCAPE)
    )
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 1

    children = list(root.find(q("w", "body")))
    names = [c.tag.rsplit("}", 1)[-1] for c in children]
    break_at = next(
        i
        for i, c in enumerate(children)
        if c.tag.endswith("}p") and c.find(f"{q('w', 'pPr')}/{q('w', 'sectPr')}") is not None
    )
    table_at = names.index("tbl")
    assert table_at < break_at or break_at == len(children) - 1, (
        "the converted text box was placed after the section break, so it now "
        f"renders under the next section's page setup. order={names}"
    )
