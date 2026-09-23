"""Does anything other than our own code accept the .docx we emit?

Every other DOCX test is self-referential: we write a package, then read it
back with the parser that wrote it. A malformed `tblPr` child order, a wrap
element in the wrong place, a stray namespace -- all would pass the entire
suite and only surface when Word or Google rejected the file, by which point
a member of staff is looking at an error instead of their worksheet.

LibreOffice is an independent OOXML implementation that owes us nothing. If it
opens our output and reads the text back out, the package is structurally
sound. That is the whole claim. It says nothing about whether Google lays the
result out nicely -- that still needs human eyes -- but it closes the "are we
even emitting a valid file" question, which currently rests on one reading of
the ECMA-376 spec.

Requires `soffice` on PATH. Skips when absent so local runs stay fast; CI
installs it, which is where this check is meant to run.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 -- fixed argv, no shell, CI-only tool
from pathlib import Path

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.docs import render_path

from .test_docx import (
    INK,
    PICTURE,
    SECTION,
    TEXTBOX,
    anchor,
    docx_with_header,
    offset,
    para,
    run,
    write_docx,
)
from .test_docx_fields import POLICY as POLICY_WITH_CONTENTS
from .test_docx_rtl import ARABIC, rtl_anchor
from .test_docx_sections import (
    A4_LANDSCAPE,
    A4_PORTRAIT,
    box,
    final_section,
    section_break_with,
    text,
)

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")
PDFTOTEXT = shutil.which("pdftotext")

needs_soffice = pytest.mark.skipif(
    SOFFICE is None,
    reason="LibreOffice not installed; this check runs in CI",
)

needs_pdftotext = pytest.mark.skipif(
    SOFFICE is None or PDFTOTEXT is None,
    reason="LibreOffice and poppler-utils not installed; this check runs in CI",
)


def rendered_text(pdf: Path) -> str:
    """Text as actually laid out on the page.

    Deliberately not LibreOffice's plain-text export: that filter walks the
    body flow and omits frame-anchored content, so a floating table -- exactly
    what this converter produces -- reads as an empty document. Extracting from
    the rendered PDF asks the stronger question anyway: did the text reach the
    page, not merely the file.
    """
    result = subprocess.run(  # noqa: S603  # nosec B603 -- fixed argv, no shell
        [PDFTOTEXT, "-layout", str(pdf), "-"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"pdftotext failed: {result.stderr}"
    return result.stdout


def rendered_page_texts(pdf: Path) -> list[str]:
    """The rendered text, split into pages.

    `pdftotext` separates pages with a form feed in both the poppler and Xpdf
    builds, which is why this reads pages that way rather than with `-bbox` or
    a second tool: the two builds share a name and do not share options, and a
    check that only works on the one CI happens to install is a check that can
    silently stop meaning anything.
    """
    pages = rendered_text(pdf).split("\f")
    while pages and not pages[-1].strip():
        pages.pop()
    return pages


def page_holding(pages: list[str], needle: str) -> int:
    """Index of the page carrying this text, or -1."""
    for index, content in enumerate(pages):
        if needle in content:
            return index
    return -1


# LibreOffice is slow to start and writes a user profile on first run.
CONVERT_TIMEOUT = 180


def soffice_convert(source: Path, target_format: str, outdir: Path) -> Path:
    """Converts with LibreOffice and fails loudly if it could not read the file."""
    outdir.mkdir(parents=True, exist_ok=True)
    profile = outdir / "profile"
    result = subprocess.run(  # noqa: S603  # nosec B603 -- fixed argv, no shell
        [
            SOFFICE,
            "--headless",
            "--norestore",
            f"-env:UserInstallation=file://{profile.as_posix()}",
            "--convert-to",
            target_format,
            "--outdir",
            str(outdir),
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=CONVERT_TIMEOUT,
        check=False,
    )
    produced = outdir / (source.stem + "." + target_format.split(":")[0])
    assert result.returncode == 0, (
        f"LibreOffice could not convert the file we emitted.\n"
        f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert produced.exists(), (
        f"LibreOffice reported success but wrote nothing.\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return produced


def convert_fixture(tmp_path: Path, body: str, header: str | None = None) -> Path:
    """Runs a fixture through the real renderer and returns the output package."""
    source = tmp_path / "source.docx"
    if header is None:
        write_docx(source, body)
    else:
        docx_with_header(source, body, header)
    out = tmp_path / "converted.docx"
    render_path(source, out, Settings())
    return out


# The constructs where a schema mistake is invisible to our own tests: a
# floating table (tblpPr/tblOverlap must precede tblW), a behind-text picture
# (wrapNone must precede docPr), a rebuilt inline drawing, and a header part.
CARD = para(
    run(TEXTBOX, h=("column", offset(-457200)), v=("paragraph", offset(228600))),
    run(PICTURE, h=("column", offset(-457200)), v=("paragraph", offset(228600))),
)
SECOND_BOX = anchor(TEXTBOX, h=("margin", offset(3000000)), v=("paragraph", offset(228600)))
LEGACY_PICT = (
    '<w:p><w:r><w:pict><v:shape style="width:120pt;height:80pt" alt="Badge">'
    '<v:imagedata r:id="rId1"/></v:shape></w:pict></w:r></w:p>'
)


@needs_soffice
def test_libreoffice_opens_what_we_emit(tmp_path):
    body = CARD + SECOND_BOX + LEGACY_PICT + anchor(INK) + SECTION
    converted = convert_fixture(tmp_path, body)
    pdf = soffice_convert(converted, "pdf", tmp_path / "out")
    assert pdf.stat().st_size > 1000, "a PDF this small suggests an empty render"
    assert pdf.read_bytes().startswith(b"%PDF"), "not a PDF"


@needs_pdftotext
def test_text_box_content_reaches_the_rendered_page(tmp_path):
    """Opening without error is weak; finding the text on the page is the check.

    A file can parse and still have lost its content -- a text box whose
    paragraphs never made it into the table cell would produce a perfectly
    valid, perfectly empty document.
    """
    body = CARD + SECOND_BOX + SECTION
    converted = convert_fixture(tmp_path, body)
    pdf = soffice_convert(converted, "pdf", tmp_path / "out")
    content = rendered_text(pdf)
    assert "Card text" in content, (
        f"the converted text box did not reach the page; got: {content!r}"
    )


@needs_pdftotext
def test_header_content_survives_the_multi_part_rewrite(tmp_path):
    """Headers are rewritten as their own part; a mistake there is easy to miss."""
    body = "<w:p><w:r><w:t>Body copy</w:t></w:r></w:p>" + SECTION
    header = anchor(TEXTBOX, h=("margin", offset(0)), v=("paragraph", offset(0)))
    converted = convert_fixture(tmp_path, body, header=header)
    pdf = soffice_convert(converted, "pdf", tmp_path / "out")
    assert "Body copy" in rendered_text(pdf)


@needs_pdftotext
def test_a_box_on_the_section_break_is_laid_out_on_its_own_sections_page(tmp_path):
    """The section fix, checked on the page rather than in our own XML.

    The XML tests assert the converted table sits before the section break.
    That is the mechanism, not the outcome: what a member of staff sees is
    which page their text box lands on. Only a real layout engine can answer
    that, and it is the one question our own parser can never be asked.

    The portrait section ends with the paragraph carrying the text box, and a
    landscape appendix follows. If the table crosses the break it is laid out
    under the appendix's page setup, so it renders on the landscape page --
    nothing errors, nothing is lost, it is simply on the wrong page.
    """
    body = (
        "<w:p><w:r><w:t>Portrait body</w:t></w:r></w:p>"
        + section_break_with(box(), size=A4_PORTRAIT)
        + text("Appendix body")
        + final_section(A4_LANDSCAPE)
    )
    converted = convert_fixture(tmp_path, body)
    pdf = soffice_convert(converted, "pdf", tmp_path / "out")
    pages = rendered_page_texts(pdf)

    portrait = page_holding(pages, "Portrait body")
    appendix = page_holding(pages, "Appendix body")
    assert portrait >= 0 and appendix >= 0, f"a section's own text is missing: {pages}"

    # Control: without a real page break the two sections share a page, and
    # every assertion below would pass while proving nothing at all.
    assert portrait != appendix, (
        f"the two sections rendered onto one page, so this fixture cannot tell them apart: {pages}"
    )

    card = page_holding(pages, "Card text")
    assert card >= 0, f"the converted text box reached no page at all: {pages}"
    assert card == portrait, (
        "the converted text box did not render on its own section's page. "
        f"expected page {portrait + 1} with 'Portrait body', found it on page "
        f"{card + 1}. pages={pages}"
    )


@needs_pdftotext
def test_a_right_to_left_box_produces_a_package_that_still_opens(tmp_path):
    """One independent reader opens a package carrying `w:bidiVisual`.

    That is the whole claim, and it is worth being exact about how narrow it
    is. This is an interoperability check for this one fixture, not schema
    validation: LibreOffice is tolerant, so it passing does not establish that
    the `CT_TblPrBase` child order is correct, only that this file did not
    defeat it. The ordering itself is asserted directly against the emitted
    XML in `test_docx_rtl.py`.

    It says nothing at all about Arabic *visual* order -- the Latin marker
    rides inside the right-to-left paragraph precisely so the assertion does
    not depend on how a text extractor handles bidirectional runs, which means
    it also cannot speak to whether those runs were laid out correctly.

    Whether Google imports any of this faithfully is a separate question again,
    and still needs human eyes on a real conversion.
    """
    body = rtl_anchor("RTLMARKER " + ARABIC) + SECTION
    converted = convert_fixture(tmp_path, body)
    pdf = soffice_convert(converted, "pdf", tmp_path / "out")
    assert "RTLMARKER" in rendered_text(pdf), "the right-to-left text box did not reach the page"


@needs_pdftotext
def test_a_document_with_a_contents_page_still_opens_and_renders(tmp_path):
    """Fields are markers in a flat run, and a broken pair is easy to emit.

    An unbalanced `fldChar` sequence is the kind of damage our own parser
    would read back happily, so this asks a reader that owes us nothing. The
    heading is checked rather than the contents entry: whether LibreOffice
    regenerates the TOC on open is its business, not a claim we make.
    """
    body = POLICY_WITH_CONTENTS
    converted = convert_fixture(tmp_path, body)
    pdf = soffice_convert(converted, "pdf", tmp_path / "out")
    assert "Safeguarding" in rendered_text(pdf), (
        "the document behind the contents page did not reach the rendered page"
    )


def _strip_empty_drawings(source: Path, destination: Path) -> int:
    """Copies a package with childless `<w:drawing>` elements removed.

    Only the drawing element, nothing else -- the run that held it stays. That
    keeps the experiment to one variable: does the leftover wrapper change the
    rendered page, or not.
    """
    import zipfile as zf
    from xml.etree.ElementTree import tostring  # nosec B405 -- our own output

    from defusedxml import ElementTree as SafeET
    from workspace_toolkit.docs import XML_DECLARATION
    from workspace_toolkit.docx import parents, q

    removed = 0
    with zf.ZipFile(source) as original, zf.ZipFile(destination, "w", zf.ZIP_DEFLATED) as out:
        for name in original.namelist():
            data = original.read(name)
            if name == "word/document.xml":
                root = SafeET.fromstring(data)
                parent_of = parents(root)
                for drawing in list(root.iter(q("w", "drawing"))):
                    if len(drawing) == 0:
                        parent_of[drawing].remove(drawing)
                        removed += 1
                data = XML_DECLARATION + tostring(root, encoding="utf-8", xml_declaration=False)
            out.writestr(name, data)
    return removed


@needs_pdftotext
def test_whether_the_empty_drawing_residue_changes_the_rendered_page(tmp_path):
    """The measurement issue #20 is gated on, rather than a speculative fix.

    Every converted anchor leaves `<w:r><w:drawing/></w:r>` behind: `_detach`
    removes the anchor from the drawing and not the drawing from the run. It is
    schema-valid, and LibreOffice has been opening it happily throughout, so
    "it looks fine" is already the evidence in hand. Only a comparison beats
    that.

    This renders the same converted document twice, once as emitted and once
    with the leftover wrappers removed, and compares the laid-out text.
    `-layout` preserves horizontal position and line breaks, so a shifted line
    or an extra one shows up as a difference.

    If this passes, the residue is inert and issue #20 closes as a note on
    `_detach`. If it fails, the residue moves content and should be removed --
    and the failure output says how. Either result is worth having; the
    present state is that nobody knows.
    """
    body = CARD + SECOND_BOX + LEGACY_PICT + anchor(INK) + SECTION
    converted = convert_fixture(tmp_path, body)

    stripped = tmp_path / "stripped.docx"
    removed = _strip_empty_drawings(converted, stripped)
    # Control: with no residue to remove the comparison proves nothing.
    assert removed >= 2, f"the fixture left no empty drawings to measure: {removed}"

    with_residue = rendered_text(soffice_convert(converted, "pdf", tmp_path / "with"))
    without_residue = rendered_text(soffice_convert(stripped, "pdf", tmp_path / "without"))

    assert with_residue == without_residue, (
        f"removing {removed} empty <w:drawing> wrappers changed the rendered "
        f"page, so the residue is not inert after all.\n"
        f"--- as emitted ---\n{with_residue!r}\n"
        f"--- stripped ---\n{without_residue!r}"
    )


@needs_soffice
def test_a_deliberately_broken_package_is_rejected(tmp_path):
    """Negative control: proves the check can actually detect a bad file.

    Without this, a green result might only mean LibreOffice is forgiving --
    the test would pass no matter what we emitted, and prove nothing.
    """
    import zipfile

    broken = tmp_path / "broken.docx"
    source = tmp_path / "ok.docx"
    write_docx(source, anchor(TEXTBOX) + SECTION)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(broken, "w") as out:
        for name in original.namelist():
            data = original.read(name)
            if name == "word/document.xml":
                data = data[: len(data) // 2]  # truncate mid-element
            out.writestr(name, data)

    with pytest.raises(AssertionError):
        soffice_convert(broken, "pdf", tmp_path / "bad")
