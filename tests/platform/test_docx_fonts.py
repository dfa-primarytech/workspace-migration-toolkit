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

import zipfile

import pytest
from defusedxml import ElementTree as SafeET
from workspace_toolkit.config import Settings
from workspace_toolkit.docx import parse, q
from workspace_toolkit.package import DOCX, Package

from .test_docx import SECTION, docx_parts, write_docx

# A font entry as Word writes it, carrying everything a matcher could use.
# PANOSE is ten bytes of classification; w:sig's usb bits claim Unicode range
# coverage, which is what constrains a substitute to a script.
FONT_TABLE = (
    '<w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<w:font w:name="Century Gothic">'
    '<w:altName w:val="Questrial"/>'
    '<w:panose1 w:val="020B0502020202020204"/>'
    '<w:charset w:val="00"/><w:family w:val="swiss"/><w:pitch w:val="variable"/>'
    '<w:sig w:usb0="A00002EF" w:usb1="4000204B" w:usb2="00000000" w:usb3="00000000" '
    'w:csb0="0000009F" w:csb1="00000000"/>'
    "</w:font>"
    '<w:font w:name="Wingdings">'
    '<w:panose1 w:val="05000000000000000000"/>'
    '<w:charset w:val="02"/><w:family w:val="auto"/><w:pitch w:val="variable"/>'
    '<w:sig w:usb0="00000000" w:usb1="10000000" w:usb2="00000000" w:usb3="00000000" '
    'w:csb0="80000000" w:csb1="00000000"/>'
    "</w:font>"
    '<w:font w:name="Sassoon Primary">'
    '<w:embedRegular r:id="rId9" w:fontKey="{00000000-0000-0000-0000-000000000000}"/>'
    "</w:font>"
    "</w:fonts>"
)


def write_docx_with_font_table(path, body: str, font_table: str = FONT_TABLE):
    """A package carrying word/fontTable.xml, which real documents always have."""
    parts = dict(docx_parts(body))
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>",
        '<Override PartName="/word/fontTable.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.fontTable+xml"/></Types>',
    )
    parts["word/fontTable.xml"] = font_table
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


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


# ------------------------------------------------- matching metadata on hand
#
# Matching at the scale of a full Google Fonts catalogue needs more than a
# name. OOXML already carries most of it in word/fontTable.xml and none of it
# is read today. These pin what is there, so the follow-up that surfaces it has
# a fixture to work against -- and so the claim "the package has this" is
# checkable rather than asserted from the spec.


def font_table_entries(tmp_path, body: str = "<w:p><w:r><w:t>A</w:t></w:r></w:p>") -> dict:
    """Reads fontTable.xml straight from the package, bypassing the parser."""
    source = write_docx_with_font_table(tmp_path / "ft.docx", body + SECTION)
    with zipfile.ZipFile(source) as archive:
        root = SafeET.fromstring(archive.read("word/fontTable.xml"))
    return {f.get(q("w", "name")): f for f in root.findall(q("w", "font"))}


def test_the_package_carries_panose_family_pitch_charset_and_coverage(tmp_path):
    """Everything a similarity scorer would want, already in the file."""
    entry = font_table_entries(tmp_path)["Century Gothic"]
    assert entry.find(q("w", "panose1")).get(q("w", "val")) == "020B0502020202020204"
    assert entry.find(q("w", "family")).get(q("w", "val")) == "swiss"
    assert entry.find(q("w", "pitch")).get(q("w", "val")) == "variable"
    assert entry.find(q("w", "charset")).get(q("w", "val")) == "00"
    assert entry.find(q("w", "altName")).get(q("w", "val")) == "Questrial"

    # usb0..usb3 claim Unicode range coverage; csb0..csb1 claim codepages.
    # These are what would constrain a substitute to a script rather than
    # trusting a family name to imply one.
    signature = entry.find(q("w", "sig"))
    assert signature.get(q("w", "usb0")) == "A00002EF"
    assert signature.get(q("w", "csb0")) == "0000009F"


def test_a_symbol_font_is_distinguishable_without_knowing_its_name(tmp_path):
    """Wingdings must never be matched by similarity, and the file says so.

    `w:charset` 02 is the symbol charset and PANOSE family kind 5 is
    "Latin Pictorial". Either marks the font as glyph-mapped rather than
    text-shaped, so a substitution turns a tick into a letter. Detecting that
    from metadata beats maintaining a list of symbol font names.
    """
    entry = font_table_entries(tmp_path)["Wingdings"]
    assert entry.find(q("w", "charset")).get(q("w", "val")) == "02"
    assert entry.find(q("w", "panose1")).get(q("w", "val")).startswith("05")


def test_an_embedded_font_is_visible_in_the_package(tmp_path):
    """An embedded family travels with the document and needs no substitute."""
    entry = font_table_entries(tmp_path)["Sassoon Primary"]
    assert entry.find(q("w", "embedRegular")) is not None


def test_a_thin_entry_stays_thin(tmp_path):
    """Word omits what it does not know, and absence must not be invented.

    An entry with no PANOSE and no signature cannot be scored for similarity.
    The honest result is UNKNOWN, not a guess derived from the name.
    """
    entry = font_table_entries(tmp_path)["Sassoon Primary"]
    assert entry.find(q("w", "panose1")) is None
    assert entry.find(q("w", "sig")) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "word/fontTable.xml is never read. Every matching property the package "
        "carries -- PANOSE, generic family, pitch, charset, Unicode coverage, "
        "alternate name, embedding -- is discarded, so the shared service can "
        "only ever be given a bare family name."
    ),
)
def test_matching_metadata_reaches_the_manifest(tmp_path):
    source = write_docx_with_font_table(
        tmp_path / "ft.docx", "<w:p><w:r><w:t>A</w:t></w:r></w:p>" + SECTION
    )
    package = Package(source, Settings(), DOCX)
    try:
        manifest = parse(package, "ft.docx", "sha")
    finally:
        package.close()
    assert manifest.get("fontMetadata"), (
        "the manifest exposes font names only, so nothing downstream can match "
        "on coverage, PANOSE or embedding"
    )
