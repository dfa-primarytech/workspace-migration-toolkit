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
