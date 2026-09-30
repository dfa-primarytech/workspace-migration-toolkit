"""Reading a converted Google Doc back, to say where to look (#53).

The tool has no AI and never claims a layout is right. What it can do is read
the document Google made and compare it, by fixed rules, with what was sent:
pictures still floating, tables lost, paragraphs that only break a page, a
page count that changed, and pages that look blank. Each finding names a kind
of defect and, where it can, the pages.

Findings go into the saved conversion report, under `readBack`, never into
`warnings`: the screen shows no notes (DECISIONS 2026-09-29). Nothing here
reads or keeps the document's text; only counts and page numbers leave it.

Not verified against live Google: the Docs and Drive answers these rules
read are the documented shapes, exercised with a fake.
"""

from __future__ import annotations

from typing import Any

from .errors import ToolkitError
from .pdf_pages import inspect_pdf


def document_facts(document: dict) -> dict[str, int]:
    """Counts from a documents.get answer, across every tab.

    With includeTabsContent the body lives in each tab's documentTab; without
    it, on the document itself. Only body-level content is counted: a table
    nested in a table is part of its outer one, as it was in the source.
    """
    facts = {"tables": 0, "inlineObjects": 0, "positionedObjects": 0, "pageBreakParagraphs": 0}
    for tab in _tabs(document):
        facts["inlineObjects"] += len(tab.get("inlineObjects") or {})
        facts["positionedObjects"] += len(tab.get("positionedObjects") or {})
        for block in (tab.get("body") or {}).get("content") or []:
            if "table" in block:
                facts["tables"] += 1
            elif "paragraph" in block and _only_breaks_a_page(block["paragraph"]):
                facts["pageBreakParagraphs"] += 1
    return facts


def _tabs(document: dict) -> list[dict]:
    if "tabs" not in document:
        return [document]
    found: list[dict] = []
    pending = list(document.get("tabs") or [])
    while pending:
        tab = pending.pop(0)
        found.append(tab.get("documentTab") or {})
        pending.extend(tab.get("childTabs") or [])
    return found


def _only_breaks_a_page(paragraph: dict) -> bool:
    """A paragraph holding a page break and nothing else but whitespace."""
    broke = False
    for element in paragraph.get("elements") or []:
        if "pageBreak" in element:
            broke = True
        elif "textRun" in element:
            if (element["textRun"].get("content") or "").strip():
                return False
        else:
            return False
    return broke


def findings(source: dict, document: dict | None, pdf: dict | None) -> list[dict[str, Any]]:
    """The rule-based findings, most useful first."""
    found: list[dict[str, Any]] = []
    if pdf is not None and pdf["probablyBlank"]:
        found.append({"code": "pages_probably_blank", "pages": pdf["probablyBlank"]})
    if document is not None:
        if document["positionedObjects"]:
            found.append(
                {"code": "pictures_still_floating", "count": document["positionedObjects"]}
            )
        if source.get("tables") is not None and document["tables"] != source["tables"]:
            found.append(
                {
                    "code": "table_count_changed",
                    "source": source["tables"],
                    "converted": document["tables"],
                }
            )
        if document["pageBreakParagraphs"]:
            found.append(
                {"code": "page_break_paragraphs", "count": document["pageBreakParagraphs"]}
            )
    # Word's saved page count is its own last layout, so evidence, not a rule.
    if pdf is not None and source.get("pages") and pdf["pages"] != source["pages"]:
        found.append(
            {"code": "page_count_changed", "source": source["pages"], "converted": pdf["pages"]}
        )
    return found


async def read_back(google, document_id: str, source: dict) -> dict[str, Any]:
    """Reads the converted document and its PDF, and returns `readBack`.

    Never raises for a read that fails: the conversion has already worked,
    and a check that couldn't run is recorded as unavailable, with Google's
    reason, rather than turning a finished conversion into a failed one.
    """
    result: dict[str, Any] = {
        "checked": [],
        "source": {"pages": source.get("pages"), "tables": source.get("tables")},
    }
    unavailable: dict[str, str] = {}

    document = None
    try:
        document = document_facts(await google.document(document_id))
        result["checked"].append("document")
        result["document"] = document
    except ToolkitError as exc:
        unavailable["document"] = exc.detail or exc.code

    pdf = None
    try:
        exported = await google.export_pdf(document_id)
    except ToolkitError as exc:
        unavailable["pdf"] = exc.detail or exc.code
    else:
        pages = inspect_pdf(exported)
        if pages is None:
            unavailable["pdf"] = "unreadable"
        else:
            pdf = {"pages": pages.pages, "probablyBlank": pages.probably_blank}
            result["checked"].append("pdf")
            result["pdf"] = pdf

    if unavailable:
        result["unavailable"] = unavailable
    result["findings"] = findings(source, document, pdf)
    return result


# ------------------------------------------------ the optional repair (#54)

ONE_POINT = {"magnitude": 1, "unit": "PT"}
NO_SPACE = {"magnitude": 0, "unit": "PT"}
REPAIRED_PARAGRAPH = {"keepLinesTogether": False, "spaceAbove": NO_SPACE, "spaceBelow": NO_SPACE}


def separators(document: dict) -> list[dict]:
    """The empty top-level paragraphs to repair, as ranges in this read.

    Only paragraphs holding nothing but whitespace, and either sitting
    directly between two tables or holding a page break: the separators Word
    documents use, which Google's import can turn into blank pages. Never the
    last block of a body, never anything inside a table, never a paragraph
    with content, and never one already repaired, so a second run changes
    nothing.
    """
    found = []
    for tab in document.get("tabs") or [{"documentTab": document}]:
        tab_id = (tab.get("tabProperties") or {}).get("tabId")
        if "tabs" in document and not tab_id:
            continue  # a range in a tabbed document must name its tab
        content = ((tab.get("documentTab") or {}).get("body") or {}).get("content") or []
        for index, block in enumerate(content[:-1]):
            paragraph = block.get("paragraph")
            if paragraph is None or not _empty(paragraph) or _repaired(paragraph):
                continue
            between_tables = (
                index > 0 and "table" in content[index - 1] and "table" in content[index + 1]
            )
            breaks = any("pageBreak" in element for element in paragraph.get("elements") or [])
            start, end = block.get("startIndex"), block.get("endIndex")
            if (between_tables or breaks) and isinstance(start, int) and isinstance(end, int):
                span = {"startIndex": start, "endIndex": end}
                found.append({**span, "tabId": tab_id} if tab_id else span)
    return found


def _empty(paragraph: dict) -> bool:
    for element in paragraph.get("elements") or []:
        if "textRun" in element:
            if (element["textRun"].get("content") or "").strip():
                return False
        elif "pageBreak" not in element:
            return False
    return True


def _repaired(paragraph: dict) -> bool:
    style = paragraph.get("paragraphStyle") or {}
    if style.get("keepLinesTogether") is not False:
        return False
    for side in ("spaceAbove", "spaceBelow"):
        if (style.get(side) or {}).get("magnitude", 0) != 0:
            return False
    runs = [e["textRun"] for e in paragraph.get("elements") or [] if "textRun" in e]
    return all((run.get("textStyle") or {}).get("fontSize") == ONE_POINT for run in runs)


def repair_requests(ranges: list[dict]) -> list[dict]:
    requests: list[dict] = []
    for span in ranges:
        requests.append(
            {
                "updateTextStyle": {
                    "range": span,
                    "textStyle": {"fontSize": ONE_POINT},
                    "fields": "fontSize",
                }
            }
        )
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": span,
                    "paragraphStyle": REPAIRED_PARAGRAPH,
                    "fields": "keepLinesTogether,spaceAbove,spaceBelow",
                }
            }
        )
    return requests


async def repair_blank_pages(google, document_id: str, read: dict) -> dict[str, Any]:
    """Repairs separator paragraphs when the read-back found blank pages.

    `read` is the read-back's own result. The document is read again here and
    every index comes from that read alone, sent with its revisionId as
    `requiredRevisionId`, so an edit in between makes Google refuse the whole
    update rather than apply it in the wrong place. Never raises: a repair
    that can't run is reported as skipped, with Google's reason.
    """
    before = read.get("pdf")
    if not before or not before["probablyBlank"]:
        return {"status": "not_needed"}
    try:
        document = await google.document(document_id)
        ranges = separators(document)
        if not ranges:
            return {"status": "nothing_to_repair"}
        revision = document.get("revisionId")
        if not revision:
            return {"status": "skipped", "reason": "no_revision"}
        await google.batch_update(document_id, repair_requests(ranges), revision)
    except ToolkitError as exc:
        return {"status": "skipped", "reason": exc.detail or exc.code}

    result: dict[str, Any] = {
        "status": "applied",
        # Each paragraph's type size and spacing were replaced: PROJECT.md's
        # word for a change made in place of the original.
        "classification": "SUBSTITUTED",
        "paragraphs": len(ranges),
        "pagesBefore": before["pages"],
        "blankBefore": before["probablyBlank"],
    }
    try:
        after = inspect_pdf(await google.export_pdf(document_id))
    except ToolkitError as exc:
        result["after"] = exc.detail or exc.code
        return result
    if after is None:
        result["after"] = "unreadable"
    else:
        result["pagesAfter"] = after.pages
        result["blankAfter"] = after.probably_blank
    return result
