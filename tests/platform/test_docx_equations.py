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

import pytest
from workspace_toolkit.docs import count_equations, source_text, verify

from .test_docx import (
    SECTION,
    TEXTBOX,
    anchor,
    offset,
    q,
    transform_body,
)

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
