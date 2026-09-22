"""The constructs the converter has never been tested against.

Development used four image-heavy worksheets. A trust's estate is mostly
policies, letters and reports, which are full of things those samples had none
of: tracked changes, comments, footnotes, numbering, bookmarks, hyperlinks and
fields.

The specific risk is `remove_empty_paragraphs`. It was written conservatively
*because* a footnote reference or a field is not `<w:t>` -- but that reasoning
has never been checked, and if it is wrong the converter silently deletes
content in exactly the documents nobody has looked at yet. Silent deletion in a
policy document is far worse than a mangled worksheet: nobody notices.

These tests assert survival, not fidelity. Whether Google renders a tracked
change well is a separate question; whether we hand it one at all is this one.
"""

from __future__ import annotations

import pytest

from .test_docx import (
    PICTURE,
    SECTION,
    TEXTBOX,
    anchor,
    offset,
    parse_body,
    q,
    transform_body,
)


def body_paragraph(inner: str) -> str:
    return f"<w:p>{inner}</w:p>"


# Each entry is (name, paragraph XML, the tag that must survive).
# All of these are paragraphs whose only content is *not* <w:t> -- precisely
# the case the emptiness rule has to get right.
NON_TEXT_CONSTRUCTS = [
    (
        "footnote reference",
        "<w:r><w:rPr/><w:footnoteReference w:id='2'/></w:r>",
        "footnoteReference",
    ),
    (
        "endnote reference",
        "<w:r><w:endnoteReference w:id='3'/></w:r>",
        "endnoteReference",
    ),
    (
        "comment anchor",
        "<w:commentRangeStart w:id='1'/><w:r><w:commentReference w:id='1'/></w:r>"
        "<w:commentRangeEnd w:id='1'/>",
        "commentReference",
    ),
    (
        "bookmark",
        "<w:bookmarkStart w:id='1' w:name='policy_top'/><w:bookmarkEnd w:id='1'/>",
        "bookmarkStart",
    ),
    (
        "symbol",
        "<w:r><w:sym w:font='Wingdings' w:char='F0FC'/></w:r>",
        "sym",
    ),
    (
        "simple field",
        "<w:fldSimple w:instr=' PAGE '><w:r><w:t>3</w:t></w:r></w:fldSimple>",
        "fldSimple",
    ),
    (
        "complex field instruction",
        "<w:r><w:fldChar w:fldCharType='begin'/></w:r>"
        "<w:r><w:instrText xml:space='preserve'> REF policy_top </w:instrText></w:r>"
        "<w:r><w:fldChar w:fldCharType='end'/></w:r>",
        "instrText",
    ),
    (
        "embedded object",
        "<w:r><w:object><v:shape style='width:10pt;height:10pt'/></w:object></w:r>",
        "object",
    ),
    (
        "inline picture",
        "<w:r><w:drawing><wp:inline><wp:extent cx='100' cy='100'/>"
        "<a:graphic><a:graphicData uri='pic'><a:blip r:embed='rId1'/>"
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>",
        "inline",
    ),
]


@pytest.mark.parametrize(
    ("name", "inner", "survives"),
    NON_TEXT_CONSTRUCTS,
    ids=[c[0].replace(" ", "_") for c in NON_TEXT_CONSTRUCTS],
)
def test_a_paragraph_holding_only_this_is_not_deleted(tmp_path, name, inner, survives):
    """Content that is not <w:t> is still content."""
    root, _ = transform_body(tmp_path, body_paragraph(inner) + SECTION)
    assert (
        root.find(".//" + q("w", survives)) is not None
        or root.find(".//" + q("wp", survives)) is not None
    ), f"{name} was deleted; the paragraph was treated as empty"


def test_tracked_changes_survive_the_transform(tmp_path):
    """Insertions and deletions carry their own markup, not plain runs.

    A policy mid-review is full of these, and losing a deletion silently
    reinstates text somebody removed on purpose.
    """
    body = (
        "<w:p>"
        "<w:ins w:id='1' w:author='a'><w:r><w:t>added wording</w:t></w:r></w:ins>"
        "<w:del w:id='2' w:author='a'><w:r><w:delText>removed wording</w:delText></w:r></w:del>"
        "</w:p>" + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    assert root.find(".//" + q("w", "ins")) is not None, "an insertion was lost"
    assert root.find(".//" + q("w", "del")) is not None, "a deletion was lost"
    assert root.find(".//" + q("w", "delText")) is not None


def test_a_paragraph_of_only_a_deletion_is_kept(tmp_path):
    """<w:delText> is not <w:t>, so this is the emptiness rule's blind spot."""
    body = (
        "<w:p><w:del w:id='1' w:author='a'>"
        "<w:r><w:delText>the whole paragraph was removed</w:delText></w:r>"
        "</w:del></w:p>" + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    assert root.find(".//" + q("w", "del")) is not None, (
        "a paragraph containing only a tracked deletion was dropped -- "
        "accepting the deletion silently rather than preserving the revision"
    )


def test_numbering_and_style_references_survive(tmp_path):
    """numPr points into numbering.xml; losing it flattens a multi-level list."""
    body = (
        "<w:p><w:pPr><w:pStyle w:val='ListParagraph'/>"
        "<w:numPr><w:ilvl w:val='2'/><w:numId w:val='7'/></w:numPr></w:pPr>"
        "<w:r><w:t>Nested item</w:t></w:r></w:p>" + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    assert root.find(".//" + q("w", "numPr")) is not None
    assert root.find(".//" + q("w", "ilvl")).get(q("w", "val")) == "2"
    assert root.find(".//" + q("w", "pStyle")) is not None


def test_a_hyperlink_keeps_its_relationship(tmp_path):
    """A hyperlink is a relationship id; drop it and the link goes nowhere."""
    body = (
        "<w:p><w:hyperlink r:id='rId9'><w:r><w:t>See the policy</w:t></w:r>"
        "</w:hyperlink></w:p>" + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    link = root.find(".//" + q("w", "hyperlink"))
    assert link is not None, "the hyperlink was lost"
    assert link.get(q("r", "id")) == "rId9", "the link target was lost"


def test_these_constructs_survive_inside_a_converted_text_box(tmp_path):
    """The text box path moves paragraphs into a table cell.

    That move is where markup gets dropped if anything rebuilds rather than
    relocates -- so check a non-trivial paragraph makes the journey intact.
    """
    rich = (
        "<w:p><w:pPr><w:numPr><w:ilvl w:val='0'/><w:numId w:val='3'/></w:numPr></w:pPr>"
        "<w:bookmarkStart w:id='4' w:name='inside_box'/>"
        "<w:ins w:id='5' w:author='a'><w:r><w:t>Box wording</w:t></w:r></w:ins>"
        "<w:r><w:footnoteReference w:id='6'/></w:r>"
        "<w:bookmarkEnd w:id='4'/></w:p>"
    )
    box = TEXTBOX.replace(
        "<w:p><w:r><w:t>Card text</w:t></w:r></w:p>",
        rich,
    )
    body = anchor(box, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 1

    cell = root.find(".//" + q("w", "tc"))
    assert cell is not None
    for tag in ("numPr", "bookmarkStart", "ins", "footnoteReference"):
        assert cell.find(".//" + q("w", tag)) is not None, (
            f"{tag} did not survive the move into the table cell"
        )


def test_converting_twice_changes_nothing_the_second_time(tmp_path):
    """Converting an already-converted document should be a no-op.

    Staff will re-run files. If the second pass rewrites anything, the
    transform is not a fixed point and repeated conversion drifts.
    """
    body = (
        anchor(TEXTBOX, h=("column", offset(-457200)), v=("paragraph", offset(0)))
        + anchor(PICTURE, h=("column", offset(3000000)), v=("paragraph", offset(0)))
        + "<w:p><w:r><w:t>Body copy</w:t></w:r></w:p>"
        + SECTION
    )
    once, first = transform_body(tmp_path, body)
    from workspace_toolkit.docs import Ids, serialise, transform

    after_one = serialise(once)
    second = transform(once, Ids())
    after_two = serialise(once)

    assert second["textboxes"] == 0, "a second pass found text boxes to convert again"
    assert after_one == after_two, "the transform is not idempotent"
    assert first["textboxes"] == 1


def test_the_parser_reports_these_documents_without_inventing_elements(tmp_path):
    """A document of prose and revisions has no floating objects to report."""
    body = (
        "<w:p><w:ins w:id='1' w:author='a'><w:r><w:t>Reviewed wording</w:t></w:r></w:ins></w:p>"
        "<w:p><w:r><w:footnoteReference w:id='2'/></w:r></w:p>" + SECTION
    )
    manifest = parse_body(tmp_path, body)
    assert manifest["pages"][0]["elements"] == []
    assert manifest["document"]["pageCount"] == 1
