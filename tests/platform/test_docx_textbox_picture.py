"""#146: a picture floating inside a text box, once the box becomes a table.

The box's paragraphs move into the new cell, so a picture floating in them
is then floating in a cell -- which #34 turns into inline cell content, as
it does everywhere else. It stayed floating: the pass decided with a map of
the tree taken before the box had moved.
"""

from __future__ import annotations

from workspace_toolkit.docs import transform

from .test_docx import A4_SECTION, PICTURE, anchor, document, offset, parse_xml, q

FLOATING = anchor(PICTURE, h=("column", offset(0)), v=("paragraph", offset(0)))


def box(content):
    return anchor(
        '<a:graphic><a:graphicData uri="x"><wps:wsp><wps:spPr/>'
        f"<wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>"
        "</wps:wsp></a:graphicData></a:graphic>",
        h=("column", offset(0)),
        v=("paragraph", offset(0)),
    )


def converted(body):
    root = parse_xml(document(body + A4_SECTION))
    report = transform(root)
    return root, report, root.find(".//" + q("w", "tc"))


def test_a_picture_floating_in_a_text_box_becomes_content_of_its_cell():
    caption = "<w:p><w:r><w:t>Caption</w:t></w:r></w:p>"
    root, report, cell = converted(box(caption + FLOATING))

    assert report["textboxes"] == 1
    assert report["picturesInlined"] == 1
    assert not list(cell.iter(q("wp", "anchor"))), "nothing should still float in the cell"
    assert len(list(cell.iter(q("wp", "inline")))) == 1
    text = "".join(t.text or "" for t in cell.iter(q("w", "t")))
    assert text == "Caption", "the box's text comes with it"


def test_a_picture_already_inline_in_a_text_box_is_left_as_it_was():
    inline = (
        '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="900000" cy="900000"/>'
        f"<wp:docPr/>{PICTURE}</wp:inline></w:drawing></w:r></w:p>"
    )
    _, report, cell = converted(box(inline))
    assert report["picturesInlined"] == 0
    assert len(list(cell.iter(q("wp", "inline")))) == 1


def test_a_picture_a_text_box_is_stacked_on_still_goes_behind_it():
    """Pictures are now decided after the boxes; a card's backing picture,
    beside its box in the same paragraph, must still be sent behind."""
    card = (
        "<w:p>"
        + box("<w:p><w:r><w:t>Card</w:t></w:r></w:p>")[5:-6]
        + anchor(PICTURE, h=("column", offset(0)), v=("paragraph", offset(0)))[5:-6]
        + "</w:p>"
    )
    root, report, _ = converted(card)
    assert report["textboxes"] == 1
    backing = root.find(".//" + q("wp", "anchor"))
    assert backing is not None and backing.get("behindDoc") == "1"
