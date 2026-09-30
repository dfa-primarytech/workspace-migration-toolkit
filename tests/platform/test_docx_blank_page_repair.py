"""The optional blank-page repair after import (#54).

Word keeps tables apart with empty paragraphs, and authors put page breaks in
empty ones. After Google's import some of these become blank pages. With the
server setting on, and only when the read-back (#53) found probably-blank
pages, the app reads the Doc afresh and, in one revision-guarded batchUpdate,
sets those separator paragraphs to 1 pt with no keep-together or spacing. It
never touches a paragraph with anything in it.

Off by default: documents.batchUpdate under drive.file is not verified live.
These tests use a fake Google.
"""

from __future__ import annotations

import asyncio
import json

from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError

from .test_docx import A4_SECTION, para, preflight_manifest, question_table, write_docx
from .test_docx_readback import BLANK, TEXT, ReadingGoogle, build_pdf

REPAIRED_TEXT = {"fontSize": {"magnitude": 1, "unit": "PT"}}
REPAIRED_PARAGRAPH = {
    "keepLinesTogether": False,
    "spaceAbove": {"magnitude": 0, "unit": "PT"},
    "spaceBelow": {"magnitude": 0, "unit": "PT"},
}
PUPIL_TEXT = "Pupil name: CONFIDENTIAL"


def run(content, style=None):
    return {"textRun": {"content": content, "textStyle": style or {}}}


def paragraph(start, end, *elements, style=None):
    return {
        "startIndex": start,
        "endIndex": end,
        "paragraph": {"elements": list(elements), "paragraphStyle": style or {}},
    }


def table(start, end):
    return {"startIndex": start, "endIndex": end, "table": {"rows": 1, "columns": 1}}


PAGE_BREAK = {"pageBreak": {}}


def worksheet(repaired=False):
    """Two tables kept apart by an empty paragraph, then a page break paragraph."""
    text_style = REPAIRED_TEXT if repaired else {}
    paragraph_style = REPAIRED_PARAGRAPH if repaired else {"keepLinesTogether": True}
    return {
        "documentId": "file-1",
        "revisionId": "rev-1",
        "tabs": [
            {
                "tabProperties": {"tabId": "t.0"},
                "documentTab": {
                    "body": {
                        "content": [
                            {"endIndex": 1, "sectionBreak": {}},
                            paragraph(1, 10, run(PUPIL_TEXT + "\n")),
                            table(10, 40),
                            paragraph(40, 41, run("\n", text_style), style=paragraph_style),
                            table(41, 70),
                            paragraph(
                                70, 72, PAGE_BREAK, run("\n", text_style), style=paragraph_style
                            ),
                            # Empty, but beside only one table: an author's blank line.
                            paragraph(72, 73, run("\n")),
                            paragraph(73, 80, run("Sheet 2\n")),
                        ]
                    },
                    "inlineObjects": {},
                    "positionedObjects": {},
                },
                "childTabs": [],
            }
        ],
    }


class RepairingGoogle(ReadingGoogle):
    def __init__(self, document, pdfs, refuse=False):
        super().__init__(document, pdfs[0])
        self.pdfs = list(pdfs)
        self.refuse = refuse
        self.updates = []

    async def export_pdf(self, file_id):
        self.read.append(("pdf", file_id))
        return self.pdfs.pop(0) if len(self.pdfs) > 1 else self.pdfs[0]

    async def batch_update(self, document_id, requests, revision_id):
        self.updates.append({"id": document_id, "requests": requests, "revision": revision_id})
        if self.refuse:
            raise ToolkitError("google_failed", "refused", 502, detail="http_400")
        return {"documentId": document_id}


def convert_with(tmp_path, google, settings=None):
    root = tmp_path / "job"
    root.mkdir()
    write_docx(root / "source.docx", para() + question_table(rows=1) + A4_SECTION)
    manifest = asyncio.run(preflight_manifest(root))
    from workspace_toolkit.docs import convert

    extra = {} if settings is None else {"settings": settings}
    return asyncio.run(convert(root, manifest, google, original_name="Worksheet", **extra))


def on():
    return Settings(docx_repair_blank_pages=True)


BEFORE = build_pdf([TEXT, BLANK, TEXT, BLANK])
AFTER = build_pdf([TEXT, TEXT])


def test_the_repair_is_off_unless_the_setting_turns_it_on(tmp_path, monkeypatch):
    assert Settings().docx_repair_blank_pages is False
    monkeypatch.delenv("WMT_DOCX_REPAIR_BLANK_PAGES", raising=False)
    assert Settings.from_env().docx_repair_blank_pages is False
    for value, expected in (("1", True), ("true", True), ("on", True), ("no", False), ("", False)):
        monkeypatch.setenv("WMT_DOCX_REPAIR_BLANK_PAGES", value)
        assert Settings.from_env().docx_repair_blank_pages is expected, value

    google = RepairingGoogle(worksheet(), [BEFORE, AFTER])
    report = convert_with(tmp_path, google)
    assert google.updates == []
    assert "repair" not in report["readBack"]


def test_the_word_pipeline_is_given_the_settings():
    from workspace_toolkit.pipelines import PIPELINES

    assert PIPELINES[".docx"].needs_settings is True


def test_separator_paragraphs_are_repaired_in_one_guarded_update(tmp_path):
    google = RepairingGoogle(worksheet(), [BEFORE, AFTER])
    report = convert_with(tmp_path, google, on())

    assert len(google.updates) == 1
    update = google.updates[0]
    assert update["revision"] == "rev-1"
    ranges = sorted(
        {
            (r[kind]["range"]["startIndex"], r[kind]["range"]["endIndex"])
            for r in update["requests"]
            for kind in r
        }
    )
    # Only the paragraph between the tables and the page-break paragraph.
    assert ranges == [(40, 41), (70, 72)]
    for request in update["requests"]:
        (kind,) = request
        assert request[kind]["range"]["tabId"] == "t.0"
        if kind == "updateTextStyle":
            assert request[kind]["textStyle"] == REPAIRED_TEXT
            assert request[kind]["fields"] == "fontSize"
        else:
            assert kind == "updateParagraphStyle"
            assert request[kind]["paragraphStyle"] == REPAIRED_PARAGRAPH
            assert request[kind]["fields"] == "keepLinesTogether,spaceAbove,spaceBelow"

    repair = report["readBack"]["repair"]
    assert repair["status"] == "applied"
    assert repair["paragraphs"] == 2
    assert repair["classification"] == "SUBSTITUTED"
    assert (repair["pagesBefore"], repair["pagesAfter"]) == (4, 2)
    assert (repair["blankBefore"], repair["blankAfter"]) == ([2, 4], [])
    assert report["status"] == "completed_with_warnings"


def test_nothing_is_changed_without_a_blank_page(tmp_path):
    google = RepairingGoogle(worksheet(), [build_pdf([TEXT, TEXT])])
    report = convert_with(tmp_path, google, on())

    assert google.updates == []
    assert report["readBack"]["repair"] == {"status": "not_needed"}


def test_running_it_again_changes_nothing(tmp_path):
    google = RepairingGoogle(worksheet(repaired=True), [BEFORE])
    report = convert_with(tmp_path, google, on())

    assert google.updates == []
    assert report["readBack"]["repair"] == {"status": "nothing_to_repair"}


def test_a_refused_update_is_reported_and_the_conversion_stands(tmp_path):
    # A changed revision is refused by Google through requiredRevisionId.
    google = RepairingGoogle(worksheet(), [BEFORE], refuse=True)
    report = convert_with(tmp_path, google, on())

    assert report["readBack"]["repair"] == {"status": "skipped", "reason": "http_400"}
    assert report["status"] == "completed_with_warnings"
    assert report["verification"] == "text_checked"


def test_the_repair_report_carries_no_document_text(tmp_path):
    google = RepairingGoogle(worksheet(), [BEFORE, AFTER])
    report = convert_with(tmp_path, google, on())

    assert report["readBack"]["repair"]["status"] == "applied"
    assert PUPIL_TEXT not in json.dumps(report)


def test_the_update_is_sent_once_with_its_revision_guard():
    import httpx
    from workspace_toolkit.google import Google

    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(503)  # a write is never repeated, even on a transient reply

    google = Google("token", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    requests = [{"updateTextStyle": {"range": {"startIndex": 1, "endIndex": 2}}}]
    try:
        asyncio.run(google.batch_update("doc", requests, "rev-9"))
    except ToolkitError:
        pass
    else:
        raise AssertionError("a refused update was treated as done")
    assert len(sent) == 1
    assert sent[0].method == "POST"
    assert sent[0].url.path == "/v1/documents/doc:batchUpdate"
    body = json.loads(sent[0].content)
    assert body == {"requests": requests, "writeControl": {"requiredRevisionId": "rev-9"}}
