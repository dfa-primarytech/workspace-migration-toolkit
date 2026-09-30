"""#113: a text box's table must not become the last thing in its container.

A text box becomes a table inserted after the paragraph it was anchored in.
When that paragraph was the last one in a cell, header, footer or the body,
the container was left ending in a table. Word always ends these with a
paragraph; the app's own trailing-paragraph rule already said so, but it was
not applied after this insertion. In the body the paragraph goes before the
body's section properties, which must stay its last child.
"""

from __future__ import annotations

from workspace_toolkit.docs import transform

from .test_docx import TEXTBOX, XMLNS, anchor, document, in_cell, local, offset, parse_xml, q

BOX = anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0)))
BODY_SECTION = "<w:sectPr><w:pgSz w:w='11906' w:h='16838'/></w:sectPr>"


def blocks(element):
    return [local(child.tag) for child in element if local(child.tag) not in ("tcPr", "sectPr")]


def test_a_text_box_alone_in_a_cell_leaves_the_cell_ending_in_a_paragraph():
    root = parse_xml(document(in_cell(BOX) + BODY_SECTION))
    report = transform(root)

    assert report["textboxes"] == 1
    cell = root.find(q("w", "body") + "/" + q("w", "tbl") + "//" + q("w", "tc"))
    assert blocks(cell)[-1] == "p", blocks(cell)


def test_a_text_box_alone_in_a_header_leaves_it_ending_in_a_paragraph():
    root = parse_xml(f"<w:hdr {XMLNS}>{BOX}</w:hdr>")
    report = transform(root)

    assert report["textboxes"] == 1
    assert blocks(root)[-1] == "p", blocks(root)


def test_the_body_ends_in_a_paragraph_before_its_section_properties():
    root = parse_xml(document(BOX + BODY_SECTION))
    transform(root)

    body = root.find(q("w", "body"))
    children = [local(child.tag) for child in body]
    assert children[-1] == "sectPr", "section properties must stay the body's last child"
    assert children[-2] == "p", children


def test_a_container_that_already_ends_in_a_paragraph_gains_nothing():
    root = parse_xml(document(in_cell(BOX + "<w:p><w:r><w:t>After</w:t></w:r></w:p>")))
    transform(root)

    # The box's own paragraph stays, holding the empty drawing left behind
    # (#20); what matters is that nothing was added after "After".
    cell = root.find(".//" + q("w", "tc"))
    assert blocks(cell) == ["p", "tbl", "p"], blocks(cell)
    last = "".join(t.text or "" for t in list(cell)[-1].iter(q("w", "t")))
    assert last == "After"
