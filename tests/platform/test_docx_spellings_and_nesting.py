"""#119: two spellings of one font, and a text box inside a text box.

1. catalogue() keeps one spelling per family, case- and space-insensitively,
   but its answers were looked up by the exact spelling. "Baskerville" was
   substituted and "baskerville", in the same document, was not.
2. Converting the outer box moves its paragraphs into a new table cell. The
   inner box was then looked for in the outer box's old content, where its
   paragraph no longer was, and conversion crashed (ValueError).
"""

from __future__ import annotations

from workspace_toolkit.docs import transform
from workspace_toolkit.docx import font_requirements

from .test_docx import (
    SECTION,
    anchor,
    converted_job,
    document,
    local,
    offset,
    open_package,
    para,
    parse_xml,
    q,
)


def run_in(font, text="Hello"):
    return f"<w:r><w:rPr><w:rFonts w:ascii='{font}'/></w:rPr><w:t>{text}</w:t></w:r>"


SPELLINGS = para(run_in("Baskerville")) + para(run_in("baskerville")) + para(run_in("BASKERVILLE"))


def test_every_spelling_of_a_family_gets_the_same_answer(tmp_path):
    package = open_package(tmp_path, SPELLINGS + SECTION)
    try:
        requirements = font_requirements(package)
    finally:
        package.close()

    families = {r["family"]: r["compatibility"] for r in requirements}
    assert set(families) == {"Baskerville", "baskerville", "BASKERVILLE"}
    assert all(answer is not None for answer in families.values()), families
    assert len({answer["replacement"] for answer in families.values()}) == 1


def test_every_spelling_of_a_family_is_substituted(tmp_path):
    report, _ = converted_job(tmp_path, SPELLINGS + SECTION)
    substitutions = report["conversion"]["fontSubstitutions"]
    assert substitutions == {
        "BASKERVILLE -> Libre Baskerville": 1,
        "Baskerville -> Libre Baskerville": 1,
        "baskerville -> Libre Baskerville": 1,
    }, substitutions


def box(content):
    return anchor(
        '<a:graphic><a:graphicData uri="x"><wps:wsp><wps:spPr/>'
        f"<wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>"
        "</wps:wsp></a:graphicData></a:graphic>",
        h=("column", offset(0)),
        v=("paragraph", offset(0)),
    )


def text_of(element):
    return "".join(t.text or "" for t in element.iter(q("w", "t")))


def test_a_text_box_inside_a_text_box_becomes_a_table_inside_its_cell():
    inner = box("<w:p><w:r><w:t>Inner</w:t></w:r></w:p>")
    outer = box("<w:p><w:r><w:t>Outer</w:t></w:r></w:p>" + inner)
    root = parse_xml(document(outer + SECTION))
    report = transform(root)

    assert report["textboxes"] == 2
    assert not list(root.iter(q("w", "txbxContent"))), "no text box is left to become a drawing"
    body = root.find(q("w", "body"))
    outer_table = next(child for child in body if local(child.tag) == "tbl")
    outer_cell = outer_table.find(".//" + q("w", "tc"))
    nested = outer_cell.find(q("w", "tbl"))
    assert nested is not None, "the inner box is a table in the outer box's cell"
    assert text_of(nested) == "Inner"
    assert text_of(outer_cell).startswith("Outer")


def test_three_boxes_deep_all_convert():
    innermost = box("<w:p><w:r><w:t>C</w:t></w:r></w:p>")
    middle = box("<w:p><w:r><w:t>B</w:t></w:r></w:p>" + innermost)
    outer = box("<w:p><w:r><w:t>A</w:t></w:r></w:p>" + middle)
    root = parse_xml(document(outer + SECTION))
    report = transform(root)

    assert report["textboxes"] == 3
    assert text_of(root) == "ABC", "every box's text survives, in order"
