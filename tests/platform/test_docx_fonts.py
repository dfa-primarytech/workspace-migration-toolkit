"""What the font list actually contains, and what it misses.

Supporting evidence for `docs/font-substitution.md`. The gaps are recorded as
executable facts rather than prose, because prose about a number drifts away
from the number.

The two gap tests are `xfail(strict=True)`: they state the behaviour a
substitution service needs, and record that it does not hold yet. When someone
resolves theme and style fonts, these turn into unexpected passes and CI says
so -- which is the point. A plain assertion of today's wrong answer would have
to be rewritten by whoever fixes it, and would read like the wrong answer was
intended.

No mapping table lives here or in the DOCX stream. Which substitute to pick is
the shared service's decision.
"""

from __future__ import annotations

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.docx import parse
from workspace_toolkit.package import DOCX, Package

from .test_docx import SECTION, write_docx


def reported_fonts(tmp_path, body: str) -> list[str]:
    source = tmp_path / "fonts.docx"
    write_docx(source, body + SECTION)
    package = Package(source, Settings(), DOCX)
    try:
        return parse(package, "fonts.docx", "sha")["fonts"]
    finally:
        package.close()


def run_with(properties: str, text: str = "Sample") -> str:
    return f"<w:p><w:r><w:rPr>{properties}</w:rPr><w:t>{text}</w:t></w:r></w:p>"


def test_a_font_named_on_the_run_is_reported(tmp_path):
    """The case that works, so the failures below mean something."""
    body = run_with('<w:rFonts w:ascii="Comic Sans MS" w:hAnsi="Comic Sans MS"/>')
    assert reported_fonts(tmp_path, body) == ["Comic Sans MS"]


def test_every_script_slot_is_collected(tmp_path):
    """One run can name a different family per script range."""
    body = run_with(
        '<w:rFonts w:ascii="Calibri" w:cs="Arabic Typesetting" w:eastAsia="MS Mincho"/>'
    )
    assert reported_fonts(tmp_path, body) == [
        "Arabic Typesetting",
        "Calibri",
        "MS Mincho",
    ]


def test_the_script_each_font_serves_is_not_recorded(tmp_path):
    """Pins a known limitation of shape rather than omission.

    All three families are found, but flattened into one list, so nothing
    records that Arabic Typesetting was serving complex script. A substitution
    service cannot apply script-specific rules to a flat set -- see
    docs/font-substitution.md.
    """
    body = run_with(
        '<w:rFonts w:ascii="Calibri" w:cs="Arabic Typesetting" w:eastAsia="MS Mincho"/>'
    )
    found = reported_fonts(tmp_path, body)
    assert all(isinstance(name, str) for name in found), (
        "if fonts ever become structured, this limitation is resolved and this "
        "test should be replaced by one asserting the script mapping"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Theme fonts are not resolved against theme1.xml. This is what Word "
        "applies by default, so an ordinary document reports no fonts at all "
        "and the preflight implies there is nothing to substitute."
    ),
)
def test_a_theme_font_resolves_to_a_real_family(tmp_path):
    body = run_with(
        '<w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi" w:cstheme="minorBidi"/>'
    )
    assert reported_fonts(tmp_path, body), (
        "a document using Word's default theme fonts reported no fonts at all"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Fonts supplied by a paragraph or character style are not resolved. A "
        "well-built template keeps its fonts in styles, so the better the "
        "document, the less this reports."
    ),
)
def test_a_font_inherited_from_a_style_is_reported(tmp_path):
    body = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p>'
    assert reported_fonts(tmp_path, body), (
        "a document whose fonts live in its styles reported no fonts at all"
    )
