"""#122: the text check reported text missing when nothing was lost.

The check compares the words of the source with the words Google read back.
Each case here is the same visible text spelled differently on each side:

* Slides keeps a slide number as autoText, which was not read at all;
* Slides splits a shape's text into one piece per style, and the pieces were
  joined with spaces, so "H2O" with a subscript became "H 2 O";
* Word keeps a no-break hyphen as an element, not a character, so "well-known"
  was read as "wellknown";
* a soft hyphen shows only at a line break, and is not part of the word.

Real loss must still be reported, and a Word symbol, whose character depends
on its font, is not guessed at.
"""

from __future__ import annotations

from workspace_toolkit.config import Settings
from workspace_toolkit.docs import render_path
from workspace_toolkit.docs import verify as verify_document
from workspace_toolkit.google import verify as verify_slides

from .test_docx import SECTION, write_docx


def slide_check(source_runs, read_back):
    """The text findings for one slide: source runs vs Slides textElements."""
    manifest = {
        "document": {"widthPt": 720, "heightPt": 405},
        "pages": [
            {
                "index": 0,
                "elements": [
                    {"type": "text", "paragraphs": [{"runs": [{"text": t} for t in source_runs]}]}
                ],
            }
        ],
    }
    presentation = {
        "pageSize": {
            "width": {"magnitude": 720, "unit": "PT"},
            "height": {"magnitude": 405, "unit": "PT"},
        },
        "slides": [{"pageElements": [{"shape": {"text": {"textElements": read_back}}}]}],
    }
    return [f for f in verify_slides(manifest, presentation) if f["code"] == "text_mismatch"]


def run(text):
    return {"textRun": {"content": text}}


def test_a_slide_number_kept_as_autotext_is_read():
    findings = slide_check(
        ["Slide ", "3"], [run("Slide "), {"autoText": {"type": "SLIDE_NUMBER", "content": "3"}}]
    )
    assert findings == []


def test_a_word_styled_partway_through_is_still_one_word():
    findings = slide_check(["H", "2", "O is water"], [run("H"), run("2"), run("O is water\n")])
    assert findings == []


def test_a_no_break_hyphen_matches_a_plain_one_on_slides():
    findings = slide_check(["a well‑known fact"], [run("a well-known fact\n")])
    assert findings == []


def test_text_really_missing_from_a_slide_is_still_reported():
    findings = slide_check(["Keep this and this"], [run("Keep this\n")])
    assert len(findings) == 1 and findings[0]["missingTokenCount"] == 2


def document_check(tmp_path, paragraph_xml, exported):
    """The text findings for a document: rendered as for conversion, with the
    tokens render() keeps, against what Drive's export would read back."""
    source = write_docx(tmp_path / "source.docx", paragraph_xml + SECTION)
    report = render_path(source, tmp_path / "converted.docx", Settings())
    findings = verify_document(report["tokens"], exported)
    return [f for f in findings if f["code"] == "text_mismatch"]


def test_a_no_break_hyphen_in_word_is_a_hyphen(tmp_path):
    body = "<w:p><w:r><w:t>a well</w:t><w:noBreakHyphen/><w:t>known fact</w:t></w:r></w:p>"
    assert document_check(tmp_path, body, "a well‑known fact\n") == []
    assert document_check(tmp_path, body, "a well-known fact\n") == []


def test_a_soft_hyphen_is_not_part_of_the_word(tmp_path):
    body = "<w:p><w:r><w:t>photo</w:t><w:softHyphen/><w:t>synthesis</w:t></w:r></w:p>"
    assert document_check(tmp_path, body, "photosynthesis\n") == []
    # An export that keeps the soft hyphen as a character reads the same.
    assert document_check(tmp_path, body, "photo­synthesis\n") == []


def test_a_word_holding_a_symbol_is_not_guessed_at(tmp_path):
    """A symbol's code means a character only in its own font (Wingdings F0FC
    is a tick; chr(0xF0FC) is a private-use character). So "5" plus a symbol
    was compared as "5", against an export reading "5" and whatever the symbol
    became, and reported missing. The word is left out now, not guessed."""
    body = (
        "<w:p><w:r><w:t>Costs 5</w:t><w:sym w:font='Symbol' w:char='F0A5'/>"
        "<w:t> today</w:t></w:r></w:p>"
    )
    assert document_check(tmp_path, body, "Costs 5∞ today\n") == []
    # The words around it are still checked.
    missing = document_check(tmp_path, body, "Costs\n")
    assert len(missing) == 1 and missing[0]["missingTokenCount"] == 1


def test_text_really_missing_from_a_document_is_still_reported(tmp_path):
    body = "<w:p><w:r><w:t>Keep this and this</w:t></w:r></w:p>"
    findings = document_check(tmp_path, body, "Keep this\n")
    assert len(findings) == 1 and findings[0]["missingTokenCount"] == 2
