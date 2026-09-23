"""Resolving what font a document actually asks for.

The audit in `docs/font-substitution.md` found that the old font list answered
a much narrower question than it appeared to. It read literal `w:rFonts`
values, so a document using Word's default theme fonts reported *no fonts at
all*, and so did one whose fonts lived in its styles -- which is what a
well-built template consists of almost entirely.

Those gaps were recorded here as strict xfails. They are closed now, so the
xfails are gone and these assert the working behaviour instead.

`fonts()` is kept as it was and still answers the narrow question, because
something depends on that shape. `font_requirements()` is the resolved view:
theme references followed, style inheritance walked, one entry per
(family, script), with matching metadata and the shared service's
recommendation attached.

No mapping table and no scorer live in this stream. Which substitute to pick
is `workspace_toolkit.fonts`; what the document needs is this.
"""

from __future__ import annotations

import zipfile

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.docx import font_requirements, is_symbol_font, parse
from workspace_toolkit.package import DOCX, Package

from .test_docx import SECTION, docx_parts, write_docx

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

# The Office theme's shape: a major font for headings, a minor one for body,
# each with a family per script. This is what w:asciiTheme="minorHAnsi" points
# at, and what Word applies when nobody picks a font.
THEME = (
    f'<a:theme {A}><a:themeElements><a:fontScheme name="Office">'
    '<a:majorFont><a:latin typeface="Calibri Light"/>'
    '<a:ea typeface="Yu Gothic Light"/><a:cs typeface="Times New Roman"/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Aptos"/>'
    '<a:ea typeface="MS Mincho"/><a:cs typeface="Arial"/></a:minorFont>'
    "</a:fontScheme></a:themeElements></a:theme>"
)

# Heading1 inherits its family from Base and adds weight, so the family is two
# steps away from the run that uses it.
STYLES = (
    f"<w:styles {W}>"
    "<w:docDefaults><w:rPrDefault><w:rPr>"
    '<w:rFonts w:asciiTheme="minorHAnsi" w:cstheme="minorBidi" w:eastAsiaTheme="minorEastAsia"/>'
    "</w:rPr></w:rPrDefault></w:docDefaults>"
    '<w:style w:styleId="Base"><w:rPr>'
    '<w:rFonts w:ascii="Century Gothic" w:hAnsi="Century Gothic"/></w:rPr></w:style>'
    '<w:style w:styleId="Heading1"><w:basedOn w:val="Base"/>'
    "<w:rPr><w:b/></w:rPr></w:style>"
    '<w:style w:styleId="Quiet"><w:rPr><w:b w:val="off"/></w:rPr></w:style>'
    "</w:styles>"
)

FONT_TABLE = (
    f"<w:fonts {W} {R}>"
    '<w:font w:name="Century Gothic">'
    '<w:altName w:val="Questrial"/><w:panose1 w:val="020B0502020202020204"/>'
    '<w:charset w:val="00"/><w:family w:val="swiss"/><w:pitch w:val="variable"/>'
    '<w:sig w:usb0="A00002EF" w:usb1="4000204B" w:usb2="00000000" w:usb3="00000000" '
    'w:csb0="0000009F" w:csb1="00000000"/></w:font>'
    '<w:font w:name="Wingdings"><w:panose1 w:val="05000000000000000000"/>'
    '<w:charset w:val="02"/><w:family w:val="auto"/></w:font>'
    '<w:font w:name="Sassoon Primary">'
    '<w:embedRegular r:id="rId9" w:fontKey="{00000000-0000-0000-0000-000000000000}"/></w:font>'
    '<w:font w:name="Nothing Known"/>'
    "</w:fonts>"
)

NUMBERING = (
    f'<w:numbering {W}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
    '<w:rPr><w:rFonts w:ascii="Wingdings" w:hAnsi="Wingdings"/></w:rPr>'
    "</w:lvl></w:abstractNum></w:numbering>"
)


def build(tmp_path, body: str, **parts: str):
    """A package with the parts a real document has and fixtures usually lack."""
    contents = dict(docx_parts(body + SECTION))
    contents["word/theme/theme1.xml"] = parts.get("theme", THEME)
    contents["word/styles.xml"] = parts.get("styles", STYLES)
    contents["word/fontTable.xml"] = parts.get("font_table", FONT_TABLE)
    if "numbering" in parts:
        contents["word/numbering.xml"] = parts["numbering"]
    if "header" in parts:
        contents["word/header1.xml"] = parts["header"]
    path = tmp_path / "fonts.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    return path


def requirements(tmp_path, body: str, **parts: str) -> dict:
    package = Package(build(tmp_path, body, **parts), Settings(), DOCX)
    try:
        return {(r["family"], r["script"]): r for r in font_requirements(package)}
    finally:
        package.close()


def run_with(properties: str, text: str = "Sample") -> str:
    return f"<w:p><w:r><w:rPr>{properties}</w:rPr><w:t>{text}</w:t></w:r></w:p>"


# ------------------------------------------------------------- resolution


def test_a_theme_font_resolves_to_a_real_family(tmp_path):
    """The gap that mattered most: Word applies these by default.

    A document where nobody picked a font still has one. Reading the literal
    attribute alone reported nothing, so the preflight implied there was
    nothing to substitute.
    """
    found = requirements(tmp_path, "<w:p><w:r><w:t>Plain body copy</w:t></w:r></w:p>")
    assert ("Aptos", "latin") in found, f"the theme's body font was not resolved: {sorted(found)}"


def test_a_font_inherited_through_a_style_chain_resolves(tmp_path):
    """Heading1 has no family of its own; Base, which it is based on, does."""
    body = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p>'
    found = requirements(tmp_path, body)
    assert ("Century Gothic", "latin") in found, (
        f"a family two steps up the basedOn chain was not found: {sorted(found)}"
    )


def test_the_default_paragraph_style_applies_without_an_explicit_style_id(tmp_path):
    """Word applies the default paragraph style when w:pStyle is absent."""
    styles = (
        f'<w:styles {W}><w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:rPr><w:rFonts w:ascii="Century Gothic"/></w:rPr>'
        "</w:style></w:styles>"
    )
    found = requirements(
        tmp_path,
        "<w:p><w:r><w:t>Body</w:t></w:r></w:p>",
        styles=styles,
        theme=f"<a:theme {A}></a:theme>",
    )
    assert ("Century Gothic", "latin") in found


def test_paragraph_mark_properties_do_not_restyle_the_paragraph_text(tmp_path):
    """w:pPr/w:rPr formats the paragraph mark, not every run in the paragraph."""
    body = (
        '<w:p><w:pPr><w:rPr><w:rFonts w:ascii="Courier New"/></w:rPr></w:pPr>'
        "<w:r><w:t>Body</w:t></w:r></w:p>"
    )
    found = requirements(
        tmp_path,
        body,
        styles=f"<w:styles {W}></w:styles>",
        theme=f"<a:theme {A}></a:theme>",
    )
    assert ("Courier New", "latin") not in found


def test_weight_is_resolved_through_the_style_too(tmp_path):
    """Whether a bold face is needed decides whether a substitute is adequate."""
    body = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p>'
    found = requirements(tmp_path, body)
    assert found[("Century Gothic", "latin")]["bold"] is True, (
        "bold came from the style rather than the run, and was missed"
    )


def test_a_style_turning_weight_off_is_not_silence(tmp_path):
    """`w:b w:val="off"` is an instruction; absence is not."""
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Quiet"/></w:pPr>'
        '<w:r><w:rPr><w:rFonts w:ascii="Century Gothic"/></w:rPr>'
        "<w:t>Quiet</w:t></w:r></w:p>"
    )
    found = requirements(tmp_path, body)
    assert found[("Century Gothic", "latin")]["bold"] is False


def test_the_run_beats_the_style_that_beats_the_default(tmp_path):
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        '<w:r><w:rPr><w:rFonts w:ascii="Comic Sans MS" w:hAnsi="Comic Sans MS"/></w:rPr>'
        "<w:t>Direct</w:t></w:r></w:p>"
    )
    found = requirements(tmp_path, body)
    assert ("Comic Sans MS", "latin") in found
    assert ("Century Gothic", "latin") not in found, (
        "the style's family was reported for a run that overrode it"
    )


def test_each_script_is_its_own_requirement(tmp_path):
    """One run names a family per script; they are not interchangeable."""
    body = run_with(
        '<w:rFonts w:ascii="Calibri" w:cs="Arabic Typesetting" w:eastAsia="MS Mincho"/>'
    )
    found = requirements(tmp_path, body)
    assert found[("Calibri", "latin")]["script"] == "latin"
    assert found[("Arabic Typesetting", "complexScript")]["script"] == "complexScript"
    assert found[("MS Mincho", "eastAsian")]["script"] == "eastAsian"


def test_a_theme_token_is_never_reported_as_a_family(tmp_path):
    """`minorHAnsi` is a pointer, and would be nonsense to look up."""
    found = requirements(tmp_path, "<w:p><w:r><w:t>Body</w:t></w:r></w:p>")
    assert not any("minorHAnsi" in family for family, _ in found), sorted(found)
    assert not any("\x00" in family for family, _ in found), (
        "the internal theme marker leaked into a reported family name"
    )


def test_a_document_that_names_no_font_anywhere_invents_none(tmp_path):
    """Without defaults, styles or direct formatting there is nothing to say."""
    found = requirements(
        tmp_path,
        "<w:p><w:r><w:t>Body</w:t></w:r></w:p>",
        styles=f"<w:styles {W}></w:styles>",
        theme=f"<a:theme {A}></a:theme>",
    )
    assert found == {}, f"a family was invented for a document that named none: {found}"


def test_a_based_on_cycle_does_not_hang(tmp_path):
    """Malformed, but it occurs, and a parser that recurses forever is worse."""
    cyclic = (
        f"<w:styles {W}>"
        '<w:style w:styleId="A"><w:basedOn w:val="B"/>'
        '<w:rPr><w:rFonts w:ascii="Calibri"/></w:rPr></w:style>'
        '<w:style w:styleId="B"><w:basedOn w:val="A"/></w:style>'
        "</w:styles>"
    )
    body = '<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr><w:r><w:t>Text</w:t></w:r></w:p>'
    found = requirements(tmp_path, body, styles=cyclic)
    assert ("Calibri", "latin") in found


# --------------------------------------------- metadata and the shared service


def test_matching_metadata_is_attached(tmp_path):
    """PANOSE and coverage come from fontTable.xml, which was never read."""
    body = run_with('<w:rFonts w:ascii="Century Gothic"/>')
    metadata = requirements(tmp_path, body)[("Century Gothic", "latin")]["metadata"]
    assert metadata["panose"] == "020B0502020202020204"
    assert metadata["family"] == "swiss"
    assert metadata["pitch"] == "variable"
    assert metadata["altName"] == "Questrial"
    assert metadata["unicodeRanges"][0] == "A00002EF"


def test_font_table_metadata_lookup_is_case_insensitive(tmp_path):
    """Family casing can differ between rFonts and fontTable.xml."""
    body = run_with('<w:rFonts w:ascii="century gothic"/>')
    metadata = requirements(tmp_path, body)[("century gothic", "latin")]["metadata"]
    assert metadata["panose"] == "020B0502020202020204"


def test_a_family_the_font_table_says_nothing_about_stays_thin(tmp_path):
    """Absence is reported as absence, not filled in with a default."""
    body = run_with('<w:rFonts w:ascii="Nothing Known"/>')
    entry = requirements(tmp_path, body)[("Nothing Known", "latin")]
    assert not entry.get("metadata"), entry.get("metadata")
    assert entry["symbol"] is False


def test_a_symbol_font_is_identified_from_its_metadata(tmp_path):
    """Detected, not listed by name: the estate holds symbol fonts nobody listed."""
    body = run_with('<w:rFonts w:ascii="Wingdings"/>')
    entry = requirements(tmp_path, body)[("Wingdings", "latin")]
    assert entry["symbol"] is True
    assert entry["compatibility"]["status"] == "UNKNOWN", (
        "a symbol font was given a text substitute, which turns a tick into a letter"
    )
    assert entry["compatibility"]["replacement"] is None


def test_an_embedded_family_is_flagged(tmp_path):
    """Embedded glyphs travel with the document and need no substitute."""
    body = run_with('<w:rFonts w:ascii="Sassoon Primary"/>')
    assert requirements(tmp_path, body)[("Sassoon Primary", "latin")]["embedded"] is True


def test_the_shared_service_supplies_the_recommendation(tmp_path):
    """This stream asks; it does not decide."""
    body = run_with('<w:rFonts w:ascii="Century Gothic"/>')
    entry = requirements(tmp_path, body)[("Century Gothic", "latin")]
    assert entry["compatibility"]["status"] in {"AVAILABLE", "SUBSTITUTED", "UNKNOWN"}
    assert entry["compatibility"]["basis"], "no basis recorded for the recommendation"


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"charset": "02"}, True),
        ({"panose": "05000000000000000000"}, True),
        ({"charset": "00", "panose": "020B0502020202020204"}, False),
        ({}, False),
        (None, False),
    ],
)
def test_symbol_detection_rules(metadata, expected):
    assert is_symbol_font(metadata) is expected


# ------------------------------------------------------------- every part


def test_fonts_in_a_header_are_requirements_too(tmp_path):
    """A letterhead's font is as real as the body's."""
    header = (
        f"<w:hdr {W}>" + run_with('<w:rFonts w:ascii="Comic Sans MS"/>', "Letterhead") + "</w:hdr>"
    )
    found = requirements(tmp_path, "<w:p><w:r><w:t>Body</w:t></w:r></w:p>", header=header)
    assert ("Comic Sans MS", "latin") in found, sorted(found)


def test_bullet_glyph_fonts_are_requirements_too(tmp_path):
    """A bullet is on every page, so a bad substitution there is seen first."""
    found = requirements(tmp_path, "<w:p><w:r><w:t>Body</w:t></w:r></w:p>", numbering=NUMBERING)
    assert ("Wingdings", "latin") in found, sorted(found)
    assert found[("Wingdings", "latin")]["symbol"] is True


# ----------------------------------------------- the narrow helper, unchanged


def reported_fonts(tmp_path, body: str) -> list[str]:
    source = tmp_path / "flat.docx"
    write_docx(source, body + SECTION)
    package = Package(source, Settings(), DOCX)
    try:
        return parse(package, "flat.docx", "sha")["fonts"]
    finally:
        package.close()


def test_the_flat_list_still_answers_its_narrower_question(tmp_path):
    body = run_with('<w:rFonts w:ascii="Comic Sans MS" w:hAnsi="Comic Sans MS"/>')
    assert reported_fonts(tmp_path, body) == ["Comic Sans MS"]


def test_the_manifest_carries_the_resolved_requirements(tmp_path):
    body = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>H</w:t></w:r></w:p>'
    package = Package(build(tmp_path, body), Settings(), DOCX)
    try:
        manifest = parse(package, "fonts.docx", "sha")
    finally:
        package.close()
    families = {r["family"] for r in manifest["fontRequirements"]}
    assert "Century Gothic" in families, (
        f"the resolved requirements did not reach the manifest: {families}"
    )
