"""Tables of contents, and the false alarm they were about to cause.

A trust's policies, handbooks and reports open with a contents page. None of
the four worksheets this converter was built on had one.

A field is a question and a cached answer. `TOC \\o "1-3" \\h \\z \\u` is the
question; the entry list with its page numbers is what Word last worked out.
Both are stored, and they are not the same kind of thing.

The transform preserves both already, which these tests pin. The problem was
in the check afterwards. Cached page numbers are ordinary `<w:t>`, so they were
counted as body text -- and Google repaginates, because its layout is not
Word's. A contents page that came back perfectly correct but renumbered would
report missing text, once per entry.

This is the exact mirror of the equations case. There, content was invisible to
the check and loss went unnoticed. Here, non-content was visible and would be
reported as loss. Both end in a report nobody can act on.

Nothing here claims Google regenerates a TOC, or does so well. That needs a
real conversion. What is claimed is that we hand over the instruction intact
and stop counting the stale answer as content.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.docs import (
    convert,
    count_regenerated_fields,
    field_name,
    render_path,
    source_text,
    verify,
)
from workspace_toolkit.docx import parse
from workspace_toolkit.package import DOCX, Package

from .test_docx import SECTION, q, transform_body, write_docx
from .test_docx_equations import FakeGoogle

TOC_INSTRUCTION = r' TOC \o "1-3" \h \z \u '


def complex_field(instruction: str, cached: str) -> str:
    """A field as Word writes it: markers in a flat run, not a subtree."""
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">{instruction}</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{cached}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def toc_entry(title: str, page: str, anchor: str = "_Toc1") -> str:
    """One contents line: title, tab leader, and a nested PAGEREF field."""
    return (
        f'<w:hyperlink w:anchor="{anchor}"><w:r><w:t>{title}</w:t></w:r>'
        "<w:r><w:tab/></w:r>"
        + complex_field(rf" PAGEREF {anchor} \h ", f"<w:r><w:t>{page}</w:t></w:r>")
        + "</w:hyperlink>"
    )


def table_of_contents(*entries: str) -> str:
    """A generated TOC, wrapped in the content control Word puts it in."""
    body = "".join(entries)
    return (
        "<w:sdt><w:sdtPr><w:docPartObj>"
        '<w:docPartGallery w:val="Table of Contents"/><w:docPartUnique/>'
        "</w:docPartObj></w:sdtPr><w:sdtContent>"
        '<w:p><w:pPr><w:pStyle w:val="TOCHeading"/></w:pPr>'
        "<w:r><w:t>Contents</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr>'
        + complex_field(TOC_INSTRUCTION, body)
        + "</w:p></w:sdtContent></w:sdt>"
    )


def heading(title: str, anchor: str = "_Toc1") -> str:
    return (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        f'<w:bookmarkStart w:id="1" w:name="{anchor}"/>'
        f"<w:r><w:t>{title}</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>'
    )


POLICY = table_of_contents(toc_entry("Safeguarding", "7")) + heading("Safeguarding") + SECTION


# ------------------------------------------------------- the field survives


def test_the_instruction_survives_exactly(tmp_path):
    """The question, not the stale answer, is what lets a reader rebuild the TOC.

    Lose the instruction and the contents page becomes dead text: it can no
    longer update, and every page number is frozen at whatever Word last
    thought.
    """
    root, _ = transform_body(tmp_path, POLICY)
    instructions = [n.text or "" for n in root.iter(q("w", "instrText"))]
    assert any("TOC" in i for i in instructions), f"the TOC instruction was lost: {instructions}"
    assert any(r'\o "1-3"' in i for i in instructions), (
        f"the TOC switches were altered, which changes which headings appear: {instructions}"
    )


def test_the_cached_display_survives_too(tmp_path):
    """Preserve both: a reader that does not regenerate still shows something."""
    root, _ = transform_body(tmp_path, POLICY)
    assert root.find(".//" + q("w", "hyperlink")) is not None, "the TOC entry link was lost"
    text = "".join(n.text or "" for n in root.iter(q("w", "t")))
    assert "Safeguarding" in text and "7" in text, (
        "the cached contents entry was stripped from the document itself; it "
        "should only be excluded from the text comparison"
    )


def test_the_content_control_and_markers_are_intact(tmp_path):
    root, _ = transform_body(tmp_path, POLICY)
    for tag in ("sdt", "docPartGallery", "fldChar", "bookmarkStart"):
        assert root.find(".//" + q("w", tag)) is not None, f"w:{tag} was lost"


def test_a_field_paragraph_is_not_collected_as_empty(tmp_path):
    """A paragraph whose only content is a field carries no <w:t> of its own."""
    body = "<w:p>" + complex_field(" PAGE ", "<w:r><w:t>3</w:t></w:r>") + "</w:p>" + SECTION
    root, _ = transform_body(tmp_path, body)
    assert root.find(".//" + q("w", "fldChar")) is not None, (
        "a paragraph containing only a field was treated as empty and removed"
    )


# --------------------------------------------- what counts as body text now


def test_cached_page_numbers_are_not_counted_as_body_text(tmp_path):
    """The false alarm this exists to prevent."""
    root, _ = transform_body(tmp_path, POLICY)
    tokens = source_text(root).split()
    assert "7" not in tokens, (
        f"a cached page number was counted as body text, so a renumbered "
        f"contents page would report missing text: {tokens}"
    )
    assert "Safeguarding" in tokens, "the real heading was dropped from the comparison"
    assert tokens.count("Safeguarding") == 1, (
        f"the TOC entry was counted as well as the heading it points at: {tokens}"
    )


def test_ordinary_text_beside_a_field_is_still_counted(tmp_path):
    """The exclusion must be narrow, or it hides real loss."""
    body = (
        "<w:p><w:r><w:t>Before</w:t></w:r>"
        + complex_field(" PAGE ", "<w:r><w:t>3</w:t></w:r>")
        + "<w:r><w:t>After</w:t></w:r></w:p>"
        + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    tokens = source_text(root).split()
    assert tokens == ["Before", "After"], f"text either side of a field was lost: {tokens}"


def test_an_authored_field_result_is_still_counted(tmp_path):
    """A HYPERLINK's display text is something a person wrote, not a computation.

    Excluding every field result would be simpler and wrong: it would stop the
    check noticing that authored words went missing.
    """
    body = (
        "<w:p>"
        + complex_field(
            r' HYPERLINK "https://example.invalid" ',
            "<w:r><w:t>Attendance policy</w:t></w:r>",
        )
        + "</w:p>"
        + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    tokens = source_text(root).split()
    assert "Attendance" in tokens and "policy" in tokens, (
        f"authored link text was excluded along with the computed fields: {tokens}"
    )


def test_a_nested_field_does_not_close_the_one_around_it(tmp_path):
    """Each TOC entry holds its own PAGEREF, so the markers nest.

    Treating the inner field's `end` as the TOC's would put everything after
    the first entry back into the comparison, and the page numbers with it.
    """
    body = (
        table_of_contents(
            toc_entry("Safeguarding", "7", "_Toc1"),
            toc_entry("Attendance", "12", "_Toc2"),
        )
        + heading("Safeguarding", "_Toc1")
        + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    tokens = source_text(root).split()
    assert "12" not in tokens and "7" not in tokens, (
        f"a page number escaped the exclusion after a nested field closed: {tokens}"
    )


def test_a_simple_field_is_handled_as_well(tmp_path):
    """<w:fldSimple> is the same idea written as one element."""
    body = (
        '<w:p><w:fldSimple w:instr=" PAGE "><w:r><w:t>4</w:t></w:r></w:fldSimple>'
        "<w:r><w:t>Body</w:t></w:r></w:p>" + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    assert source_text(root).split() == ["Body"], source_text(root)


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        (TOC_INSTRUCTION, "TOC"),
        (" PAGEREF _Toc1 ", "PAGEREF"),
        (r' HYPERLINK "x" ', "HYPERLINK"),
        ("   ", ""),
    ],
)
def test_field_names_are_read_from_the_instruction(instruction, expected):
    assert field_name(instruction) == expected


# ------------------------------------------------------------ the diagnostic


def test_fields_needing_regeneration_are_counted(tmp_path):
    """Two here: the TOC and the PAGEREF inside its single entry."""
    root, _ = transform_body(tmp_path, POLICY)
    assert count_regenerated_fields(root) == 2


def test_a_document_of_plain_prose_counts_none(tmp_path):
    root, _ = transform_body(tmp_path, "<w:p><w:r><w:t>Plain prose</w:t></w:r></w:p>" + SECTION)
    assert count_regenerated_fields(root) == 0


def test_the_warning_tells_a_reader_to_check_the_contents_page(tmp_path):
    findings = verify({}, "", regenerated_fields=4)
    raised = next(f for f in findings if f["code"] == "fields_need_regeneration")
    assert raised["fieldCount"] == 4
    assert set(raised) <= {"code", "message", "fieldCount", "classification"}, (
        f"the warning carries document content: {sorted(raised)}"
    )


def test_a_document_without_such_fields_says_nothing(tmp_path):
    codes = {f["code"] for f in verify({}, "", regenerated_fields=0)}
    assert "fields_need_regeneration" not in codes


def test_the_count_reaches_the_conversion_report_and_its_warning(tmp_path):
    """Wiring, end to end: render writes it, convert reads it, the report says it."""
    job = tmp_path / "job"
    result = job / "result"
    result.mkdir(parents=True)
    source = job / "source.docx"
    write_docx(source, POLICY)

    package = Package(source, Settings(), DOCX)
    try:
        manifest = parse(package, "source.docx", "sha")
    finally:
        package.close()

    render_report = render_path(source, result / "converted.docx", Settings())
    assert render_report["regeneratedFields"] == 2
    (result / "render.json").write_text(json.dumps(render_report), encoding="utf-8")

    report = asyncio.run(convert(job, manifest, FakeGoogle()))
    assert report["conversion"]["regeneratedFields"] == 2
    codes = {w["code"] for w in report["warnings"]}
    assert "fields_need_regeneration" in codes, (
        f"no field warning in the report a person reads: {sorted(codes)}"
    )
