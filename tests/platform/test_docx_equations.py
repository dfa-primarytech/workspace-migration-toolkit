"""Equations, and the hole they left in the safety net.

The four worksheets this converter was built on are image-heavy infant
material. A secondary maths or science department's documents are full of
something none of them contained: OMML equations.

Two separate questions, and only one of them has a good answer.

**Do equations survive our transform?** Yes, and for the same reason
right-to-left text does -- the converter relocates markup rather than
rebuilding it. Pinned here, including the case that matters most: an equation
inside a text box, which is the one construct we take apart and reassemble.

**Would we notice if Google dropped them?** No, and that is the finding. The
post-import check compares a multiset of `<w:t>` tokens; equation text lives in
`<m:t>` and was invisible to it. A maths worksheet could arrive with every
equation gone and the report would say nothing was missing.

Folding `<m:t>` into that token count looks like the fix and is not -- see
`count_equations`. These tests cover the reporting route taken instead.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.docs import convert, count_equations, render_path, source_text, verify
from workspace_toolkit.docx import parse
from workspace_toolkit.google import DOCS_MIME
from workspace_toolkit.package import DOCX, Package

from .test_docx import (
    SECTION,
    TEXTBOX,
    anchor,
    docx_with_header,
    offset,
    q,
    transform_body,
)


class FakeGoogle:
    """The smallest double convert() will accept.

    Deliberately not a mock of the whole Drive API: this test is about one
    number surviving the trip from render.json into the report, and a double
    that asserts on upload bodies would fail for reasons that have nothing to
    do with equations.
    """

    async def request(self, method: str, url: str, **kwargs: object) -> dict:
        return {"importFormats": {DOCX.mime: [DOCS_MIME]}}

    async def folder(self, job_name: str = "Conversion") -> str:
        return "folder1"

    async def upload(self, path: Path, name: str, mime: str, folder: str, **kwargs: object) -> dict:
        return {"id": "file-" + name}

    async def export_text(self, file_id: str) -> str:
        # Whatever the body text was; equation content is deliberately absent,
        # which is the very uncertainty the warning exists to cover.
        return ""


MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

# A fraction, because it nests: a converter that flattened structure would
# keep the characters and lose the arrangement, and the counts would not say.
FRACTION = (
    f"<m:oMath xmlns:m='{MATH_NS}'>"
    "<m:f><m:num><m:r><m:t>x</m:t></m:r></m:num>"
    "<m:den><m:r><m:t>y</m:t></m:r></m:den></m:f>"
    "</m:oMath>"
)
DISPLAY_EQUATION = f"<m:oMathPara xmlns:m='{MATH_NS}'>{FRACTION}</m:oMathPara>"


def qm(tag: str) -> str:
    return f"{{{MATH_NS}}}{tag}"


# ----------------------------------------------------------------- survival


def test_a_paragraph_that_is_only_an_equation_is_not_deleted(tmp_path):
    """`<m:oMathPara>` is not `<w:t>`, so this is the emptiness rule's blind spot.

    Exactly the risk already covered for footnotes and fields: a paragraph
    holding no text runs at all, which must not be mistaken for an empty one.
    """
    root, _ = transform_body(tmp_path, f"<w:p>{DISPLAY_EQUATION}</w:p>" + SECTION)
    assert root.find(".//" + qm("oMath")) is not None, (
        "a paragraph containing only an equation was treated as empty and removed"
    )


def test_an_equation_inline_with_text_keeps_both(tmp_path):
    body = f"<w:p><w:r><w:t>Solve</w:t></w:r>{FRACTION}</w:p>" + SECTION
    root, _ = transform_body(tmp_path, body)
    assert root.find(".//" + qm("oMath")) is not None, "the inline equation was lost"
    assert "Solve" in source_text(root), "the surrounding text was lost"


def test_an_equation_survives_the_move_into_a_converted_text_box(tmp_path):
    """The text box path is the only place paragraphs are relocated.

    A worked example in a coloured box is ordinary in a maths worksheet, and
    this is where a rebuild rather than a relocation would quietly drop it.
    """
    box = TEXTBOX.replace(
        "<w:p><w:r><w:t>Card text</w:t></w:r></w:p>",
        f"<w:p>{DISPLAY_EQUATION}</w:p>",
    )
    body = anchor(box, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 1

    cell = root.find(".//" + q("w", "tc"))
    assert cell is not None
    assert cell.find(".//" + qm("oMath")) is not None, (
        "the equation did not survive the move into the table cell"
    )


def test_the_structure_survives_and_not_merely_the_characters(tmp_path):
    """Keeping "x" and "y" while losing the fraction is not keeping the equation."""
    root, _ = transform_body(tmp_path, f"<w:p>{DISPLAY_EQUATION}</w:p>" + SECTION)
    fraction = root.find(".//" + qm("f"))
    assert fraction is not None, "the fraction element was flattened away"
    assert fraction.find(qm("num")) is not None, "the numerator was lost"
    assert fraction.find(qm("den")) is not None, "the denominator was lost"


def test_equations_are_left_exactly_as_they_were(tmp_path):
    """We do not rewrite equations, so a second pass must find nothing to do."""
    body = f"<w:p>{DISPLAY_EQUATION}</w:p>" + SECTION
    root, _ = transform_body(tmp_path, body)
    from workspace_toolkit.docs import Ids, serialise, transform

    once = serialise(root)
    transform(root, Ids())
    assert serialise(root) == once, "a second pass altered the equation"


def test_equations_keep_the_conventional_namespace_prefix(tmp_path):
    """Unregistered, OMML re-serialises under a generated prefix like `ns1`.

    Still valid, and Word tolerates any prefix -- but it rewrites every
    equation in the output for no reason, which makes a diff between two
    conversions unreadable at exactly the moment somebody is trying to work
    out what a change did. The same policy already applies to the other
    namespaces this module emits.
    """
    from workspace_toolkit.docs import serialise

    root, _ = transform_body(tmp_path, f"<w:p>{DISPLAY_EQUATION}</w:p>" + SECTION)
    emitted = serialise(root).decode("utf-8")
    assert "<m:oMath" in emitted, (
        f"equations were not written under the conventional 'm' prefix: "
        f"{emitted[emitted.find('oMath') - 40 : emitted.find('oMath') + 20]!r}"
    )


# ------------------------------------------------------------- the blind spot


def test_equation_text_is_not_counted_as_body_text(tmp_path):
    """Pins the deliberate omission, so it cannot be "fixed" by accident.

    Folding `<m:t>` into this would make every maths document report missing
    text whenever Google's export omits equation content -- a warning that
    fires on documents that lost nothing. The same reasoning already keeps
    headers out of this count.
    """
    body = f"<w:p><w:r><w:t>Solve</w:t></w:r>{FRACTION}</w:p>" + SECTION
    root, _ = transform_body(tmp_path, body)
    text = source_text(root)
    assert "Solve" in text
    assert "x" not in text.split(), f"equation text leaked into the token count: {text!r}"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (f"<w:p>{DISPLAY_EQUATION}</w:p>", 1),
        (f"<w:p>{FRACTION}</w:p><w:p>{FRACTION}</w:p>", 2),
        ("<w:p><w:r><w:t>No maths here</w:t></w:r></w:p>", 0),
    ],
    ids=["display", "two_inline", "none"],
)
def test_equations_are_counted(tmp_path, body, expected):
    root, _ = transform_body(tmp_path, body + SECTION)
    assert count_equations(root) == expected


# ------------------------------------------------------------- the wiring
#
# count_equations and verify are both correct in isolation above. Nothing there
# proves the number travels from one to the other, and a count that never
# reaches the report is the same as no count at all.


def test_render_counts_equations_in_every_part_not_just_the_body(tmp_path):
    """Headers are processed too, and an equation in one is equally unverified.

    The token comparison is body-only for a real reason -- Drive's plain-text
    export does not reliably include headers, so comparing them would invent
    mismatches. That reasoning is about *text comparison* and says nothing
    about where an equation can be, but the count originally sat inside the
    same body-only branch and inherited the restriction by accident.
    """
    source = tmp_path / "source.docx"
    docx_with_header(
        source,
        f"<w:p>{DISPLAY_EQUATION}</w:p>" + SECTION,
        header=f"<w:p>{FRACTION}</w:p>",
    )
    report = render_path(source, tmp_path / "out.docx", Settings())
    assert report["equations"] == 2, (
        f"expected the body's equation and the header's, got {report['equations']}"
    )


def test_an_equation_only_in_a_header_is_still_counted(tmp_path):
    """The case that was silently zero: no body equation at all."""
    source = tmp_path / "header-only.docx"
    docx_with_header(
        source,
        "<w:p><w:r><w:t>Ordinary body copy</w:t></w:r></w:p>" + SECTION,
        header=f"<w:p>{FRACTION}</w:p>",
    )
    report = render_path(source, tmp_path / "out.docx", Settings())
    assert report["equations"] == 1, (
        "an equation in a header was not counted, so the document would be "
        "reported as containing none and no warning would be raised"
    )


def test_the_count_reaches_the_conversion_report_and_its_warning(tmp_path):
    """End to end through the mocked Google path.

    Everything else here tests a function. This tests the wiring: render
    writes a count, convert reads it back out of render.json, and the warning
    reaches the report a person actually sees. Break any link in that chain
    and every other test in this file still passes.
    """
    job = tmp_path / "job"
    result = job / "result"
    result.mkdir(parents=True)

    source = job / "source.docx"
    docx_with_header(
        source,
        f"<w:p>{DISPLAY_EQUATION}</w:p>" + SECTION,
        header=f"<w:p>{FRACTION}</w:p>",
    )
    package = Package(source, Settings(), DOCX)
    try:
        manifest = parse(package, "source.docx", "sha")
    finally:
        package.close()

    render_report = render_path(source, result / "converted.docx", Settings())
    (result / "render.json").write_text(json.dumps(render_report), encoding="utf-8")

    report = asyncio.run(convert(job, manifest, FakeGoogle()))

    assert report["status"] == "completed_with_warnings"
    assert report["conversion"]["equations"] == 2, (
        f"the count did not reach the conversion report: {report.get('conversion')}"
    )
    codes = {w["code"] for w in report["warnings"]}
    assert "equations_not_verified" in codes, (
        f"no equation warning in the report a person reads: {sorted(codes)}"
    )
    raised = next(w for w in report["warnings"] if w["code"] == "equations_not_verified")
    assert raised["equationCount"] == 2


def test_a_document_with_equations_warns_that_they_were_not_checked(tmp_path):
    """The point of the count: say what is not known, rather than nothing."""
    findings = verify({"Solve": 1}, "Solve", equations=3)
    codes = {f["code"] for f in findings}
    assert "equations_not_verified" in codes, (
        "a document containing equations gave no indication they were unverified"
    )
    equation_warning = next(f for f in findings if f["code"] == "equations_not_verified")
    assert equation_warning["equationCount"] == 3


def test_a_document_without_equations_says_nothing_about_them(tmp_path):
    """A warning that appears on every document is one nobody reads."""
    findings = verify({"Solve": 1}, "Solve", equations=0)
    assert "equations_not_verified" not in {f["code"] for f in findings}


def test_the_warning_does_not_carry_the_equation_itself(tmp_path):
    """Reports are written to Drive, so they must not contain document content.

    The existing token check reports counts for exactly this reason, and an
    equation warning has to hold the same line.
    """
    findings = verify({}, "", equations=2)
    equation_warning = next(f for f in findings if f["code"] == "equations_not_verified")
    assert set(equation_warning) <= {"code", "message", "equationCount", "classification"}, (
        f"unexpected keys in the warning: {sorted(equation_warning)}"
    )
