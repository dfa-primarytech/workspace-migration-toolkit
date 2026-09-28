"""Blank lines are the author's layout, and words are compared as a reader sees them.

Issue #42: the empty-paragraph pass deleted every blank line in a document --
worksheet answer space, spacing in letters, empty paragraphs carrying a page
break -- and emptied headers into `<w:hdr/>`. It exists only to clear up
paragraphs *this converter* emptied.

Issue #43: the text check joined every `<w:t>` with a space and counted
`mc:Fallback`, so a word split across runs and every text box reported text
as missing that was never lost.
"""

from __future__ import annotations

import re

from defusedxml import ElementTree
from workspace_toolkit.docs import source_text

from .test_docx import INK, SECTION, XMLNS, anchor, q, render_with_header, transform_body

TEXT = "<w:p><w:r><w:t>{}</w:t></w:r></w:p>"
PARAGRAPH = re.compile(r"<w:p[\s/>]")


def body_paragraphs(root):
    return root.find(q("w", "body")).findall(q("w", "p"))


# ------------------------------------------------------------------ #42


def test_the_authors_blank_lines_survive(tmp_path):
    body = (
        TEXT.format("Name")
        + "<w:p/>"
        + "<w:p><w:pPr><w:spacing w:after='0'/></w:pPr></w:p>"
        + "<w:p><w:r><w:rPr><w:sz w:val='28'/></w:rPr></w:r></w:p>"
        + TEXT.format("Answer")
        + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    assert len(body_paragraphs(root)) == 6, "blank lines the author typed were removed"


def test_an_empty_page_break_paragraph_survives(tmp_path):
    body = (
        TEXT.format("Page one")
        + "<w:p><w:pPr><w:pageBreakBefore/></w:pPr></w:p>"
        + TEXT.format("Page two")
        + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    assert root.find(".//" + q("w", "pageBreakBefore")) is not None, "two pages were merged"


def test_a_paragraph_emptied_by_the_converter_is_still_removed(tmp_path):
    # The pass's real job: a paragraph whose only content was ink has nothing
    # left once the ink is gone, and keeping it adds a line nobody typed.
    body = TEXT.format("Before") + anchor(INK) + TEXT.format("After") + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["ink"] == 1
    texts = [t.text for p in body_paragraphs(root) for t in p.iter(q("w", "t"))]
    assert texts == ["Before", "After"]
    assert len(body_paragraphs(root)) == 3, "the emptied paragraph was left behind"


def test_an_empty_header_stays_valid(tmp_path):
    header = "<w:p><w:pPr><w:pStyle w:val='Header'/></w:pPr></w:p>"
    _, parts = render_with_header(tmp_path, SECTION, header)
    assert PARAGRAPH.search(parts["word/header1.xml"]), "the header was left with no paragraph"


def test_a_header_emptied_by_the_converter_keeps_one_paragraph(tmp_path):
    _, parts = render_with_header(tmp_path, SECTION, anchor(INK))
    assert PARAGRAPH.search(parts["word/header1.xml"]), "<w:hdr/> is not a valid header"


# ------------------------------------------------------------------ #43


def tokens(body):
    root = ElementTree.fromstring(f"<w:document {XMLNS}><w:body>{body}</w:body></w:document>")
    return source_text(root).split()


def test_a_word_split_across_runs_is_one_token():
    body = (
        "<w:p><w:r><w:t>Photo</w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>synthesis</w:t></w:r></w:p>"
    )
    assert tokens(body) == ["Photosynthesis"]


def test_spaces_inside_runs_still_separate_words():
    body = "<w:p><w:r><w:t xml:space='preserve'>The </w:t></w:r><w:r><w:t>cat</w:t></w:r></w:p>"
    assert tokens(body) == ["The", "cat"]


def test_paragraphs_tabs_and_breaks_separate_words():
    body = (
        "<w:p><w:r><w:t>one</w:t><w:tab/><w:t>two</w:t><w:br/><w:t>three</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>four</w:t></w:r></w:p>"
    )
    assert tokens(body) == ["one", "two", "three", "four"]


def test_a_text_box_is_counted_once_not_with_its_fallback():
    body = (
        "<w:p><w:r><mc:AlternateContent>"
        "<mc:Choice Requires='wps'><w:drawing><w:txbxContent>"
        "<w:p><w:r><w:t>Box text</w:t></w:r></w:p>"
        "</w:txbxContent></w:drawing></mc:Choice>"
        "<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>"
        "<w:p><w:r><w:t>Box text</w:t></w:r></w:p>"
        "</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>"
        "</mc:AlternateContent></w:r></w:p>"
    )
    assert tokens(body) == ["Box", "text"]


def test_text_inside_a_box_does_not_fuse_with_the_text_around_it():
    body = (
        "<w:p><w:r><w:t>Before</w:t></w:r><w:r><w:drawing><w:txbxContent>"
        "<w:p><w:r><w:t>Inside</w:t></w:r></w:p>"
        "</w:txbxContent></w:drawing></w:r><w:r><w:t>After</w:t></w:r></w:p>"
    )
    assert tokens(body) == ["Before", "Inside", "After"]


def test_hidden_text_is_not_expected_in_the_export():
    body = (
        "<w:p><w:r><w:t xml:space='preserve'>Shown </w:t></w:r>"
        "<w:r><w:rPr><w:vanish/></w:rPr><w:t>hidden</w:t></w:r></w:p>"
        "<w:p><w:r><w:rPr><w:vanish w:val='0'/></w:rPr><w:t>unhidden</w:t></w:r></w:p>"
    )
    assert tokens(body) == ["Shown", "unhidden"]
