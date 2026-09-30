"""#114: a page size written as a decimal or with a unit.

Word writes whole twips, but other generators write `w:w="11906.0"` or
`w:w="210mm"`, and reading either with int() crashed analysis outright. A size
the document states but that cannot be read at all is refused with a clear
message, never replaced by A4: the document would be laid out on a page it
never had.
"""

from __future__ import annotations

import pytest
from workspace_toolkit.docs import transform
from workspace_toolkit.errors import ToolkitError

from .test_docx import document, parse_body, parse_xml, q, wide_table


def section(width, height):
    return (
        f'<w:p><w:pPr><w:sectPr><w:pgSz w:w="{width}" w:h="{height}"/>'
        '<w:pgMar w:left="1440" w:right="1440" w:top="1440" w:bottom="1440"/>'
        "</w:sectPr></w:pPr></w:p>"
    )


def page(tmp_path, width, height):
    manifest = parse_body(tmp_path, "<w:p/>" + section(width, height))
    first = manifest["pages"][0]
    return round(first["widthPt"], 1), round(first["heightPt"], 1)


def test_a_decimal_page_size_is_read(tmp_path):
    assert page(tmp_path, "11906.0", "16838.0") == (595.3, 841.9)


@pytest.mark.parametrize(
    ("width", "height"),
    [("210mm", "297mm"), ("21cm", "29.7cm"), ("8.268in", "11.693in"), ("595.3pt", "841.9pt")],
)
def test_a_page_size_with_a_unit_is_read(tmp_path, width, height):
    assert page(tmp_path, width, height) == pytest.approx((595.3, 841.9), abs=0.1)


@pytest.mark.parametrize("width", ["wide", "0", "-11906"])
def test_an_unreadable_page_size_is_refused_not_replaced_by_a4(tmp_path, width):
    with pytest.raises(ToolkitError) as raised:
        page(tmp_path, width, "16838")
    assert raised.value.code == "invalid_page_size"
    assert "page size" in raised.value.message


def test_a_page_width_with_a_unit_still_measures_the_table():
    """The renderer reads the same page through the same rule: 210mm leaves
    9026 twips between 1in margins, so a 12000-twip table is narrowed."""
    root = parse_xml(document(wide_table() + section("210mm", "297mm")))
    report = transform(root)

    assert report["tablesNarrowed"] == 1
    columns = [int(c.get(q("w", "w"))) for c in root.iter(q("w", "gridCol"))]
    assert sum(columns) <= 9026
