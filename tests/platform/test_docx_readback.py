"""Reading the converted Google Doc back, to say where to look (#53).

After import, the document is read with the Docs API and exported as a PDF.
Rule-based checks compare what came back with what was sent, and the findings
go into the saved conversion report only, never on screen (DECISIONS
2026-09-29). None of this has been run against live Google: these tests use a
fake Google and PDFs built here.
"""

from __future__ import annotations

import asyncio
import json
import zipfile
import zlib

import httpx
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.google import Google

from .test_docx import (
    A4_SECTION,
    FakeGoogle,
    para,
    preflight_manifest,
    question_table,
    write_docx,
)

# ----------------------------------------------------------------- PDFs


def build_pdf(contents: list[bytes], object_stream: bool = False, nested: bool = False) -> bytes:
    """A small PDF with one page per content stream, compressed as Google's are.

    With `object_stream`, the catalog, page tree and pages are stored inside a
    compressed object stream, as PDF 1.5 allows. With `nested`, the first two
    pages sit in a page tree of their own under the root.
    """
    count = len(contents)
    first_page = 3 if not nested else 4
    page_ids = [first_page + n * 2 for n in range(count)]
    content_ids = [page + 1 for page in page_ids]

    def kids(ids):
        return b"[" + b" ".join(b"%d 0 R" % i for i in ids) + b"]"

    dictionaries: dict[int, bytes] = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    if nested:
        dictionaries[2] = (
            b"<< /Type /Pages /Kids " + kids([3, *page_ids[2:]]) + b" /Count %d >>" % count
        )
        dictionaries[3] = (
            b"<< /Type /Pages /Parent 2 0 R /Kids " + kids(page_ids[:2]) + b" /Count 2 >>"
        )
    else:
        dictionaries[2] = b"<< /Type /Pages /Kids " + kids(page_ids) + b" /Count %d >>" % count
    for page, content in zip(page_ids, content_ids, strict=True):
        dictionaries[page] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R >>" % content
        )

    streams = {}
    for content, raw in zip(content_ids, contents, strict=True):
        streams[content] = zlib.compress(raw)

    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")

    def emit(number: int, body: bytes) -> None:
        out.extend(b"%d 0 obj\n" % number + body + b"\nendobj\n")

    def stream(dictionary: bytes, data: bytes) -> bytes:
        return dictionary[:-2] + b" /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"

    for number, data in streams.items():
        emit(number, stream(b"<< /Filter /FlateDecode >>", data))
    if object_stream:
        numbers = sorted(dictionaries)
        header, body, offset = [], b"", 0
        for number in numbers:
            header.append(b"%d %d" % (number, offset))
            body += dictionaries[number] + b"\n"
            offset = len(body)
        head = b" ".join(header) + b"\n"
        packed = zlib.compress(head + body)
        emit(
            max([*dictionaries, *streams]) + 1,
            stream(
                b"<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode >>"
                % (len(numbers), len(head)),
                packed,
            ),
        )
        out.extend(b"trailer\n<< /Root 1 0 R >>\n%%EOF\n")
    else:
        for number, dictionary in sorted(dictionaries.items()):
            emit(number, dictionary)
        out.extend(b"trailer\n<< /Size %d /Root 1 0 R >>\n%%%%EOF\n" % (len(dictionaries) + 1))
    return bytes(out)


TEXT = b"BT /F1 12 Tf 72 720 Td (Question 1) Tj ET"
BLANK = b"q 1 0 0 1 0 0 cm Q"
PICTURE = b"q 200 0 0 100 72 600 cm /Im1 Do Q"


def test_pages_are_counted_and_a_page_with_nothing_drawn_is_flagged():
    from workspace_toolkit.pdf_pages import inspect_pdf

    found = inspect_pdf(build_pdf([TEXT, BLANK, PICTURE]))
    assert found is not None
    assert found.pages == 3
    assert found.probably_blank == [2]


def test_pages_stored_in_an_object_stream_are_read_too():
    from workspace_toolkit.pdf_pages import inspect_pdf

    found = inspect_pdf(build_pdf([BLANK, TEXT], object_stream=True))
    assert found is not None
    assert found.pages == 2
    assert found.probably_blank == [1]


def test_pages_are_numbered_in_reading_order_through_a_nested_tree():
    from workspace_toolkit.pdf_pages import inspect_pdf

    found = inspect_pdf(build_pdf([TEXT, BLANK, TEXT, BLANK], nested=True))
    assert found is not None
    assert found.pages == 4
    assert found.probably_blank == [2, 4]


def test_something_that_is_not_a_pdf_gives_no_answer():
    from workspace_toolkit.pdf_pages import inspect_pdf

    assert inspect_pdf(b"not a pdf at all") is None
    assert inspect_pdf(build_pdf([TEXT])[:40]) is None


def test_a_page_that_cannot_be_decoded_is_not_called_blank():
    from workspace_toolkit.pdf_pages import inspect_pdf

    data = build_pdf([TEXT, BLANK]).replace(b"/FlateDecode", b"/LZWDecode", 2)
    found = inspect_pdf(data)
    assert found is not None
    assert found.pages == 2
    assert found.probably_blank == []


# ----------------------------------------------------- the Doc read back


SECRET = "Pupil name: CONFIDENTIAL"


def paragraph(*elements):
    return {"paragraph": {"elements": list(elements)}}


def text(content):
    return {"textRun": {"content": content}}


PAGE_BREAK = {"pageBreak": {}}


def docs_document(content, positioned=0, inline=0):
    """A documents.get answer with includeTabsContent, one tab."""
    return {
        "documentId": "file-1",
        "tabs": [
            {
                "documentTab": {
                    "body": {"content": content},
                    "inlineObjects": {f"kix.i{n}": {} for n in range(inline)},
                    "positionedObjects": {f"kix.p{n}": {} for n in range(positioned)},
                },
                "childTabs": [],
            }
        ],
    }


class ReadingGoogle(FakeGoogle):
    def __init__(self, document=None, pdf=None, fail=None, **kwargs):
        super().__init__(**kwargs)
        self.docs_answer = document
        self.pdf = pdf
        self.fail = fail
        self.read = []

    async def document(self, document_id):
        self.read.append(("document", document_id))
        if self.fail == "document":
            raise ToolkitError("readback_unavailable", "refused", 502, detail="http_403")
        return self.docs_answer

    async def export_pdf(self, file_id):
        self.read.append(("pdf", file_id))
        if self.fail == "pdf":
            raise ToolkitError("readback_unavailable", "refused", 502, detail="export_too_large")
        return self.pdf


APP_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"


def job_with(tmp_path, body, google, pages=None):
    root = tmp_path / "job"
    root.mkdir()
    source = write_docx(root / "source.docx", body + A4_SECTION)
    if pages is not None:
        with zipfile.ZipFile(source) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts["_rels/.rels"] = parts["_rels/.rels"].replace(
            b"</Relationships>",
            f'<Relationship Id="app" Type="{APP_REL}" Target="docProps/app.xml"/>'
            "</Relationships>".encode(),
        )
        parts["docProps/app.xml"] = (
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'extended-properties"><Pages>{pages}</Pages></Properties>'
        ).encode()
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
    manifest = asyncio.run(preflight_manifest(root))
    from workspace_toolkit.docs import convert

    return asyncio.run(convert(root, manifest, google, original_name="Worksheet"))


def codes(report):
    return {finding["code"]: finding for finding in report["readBack"]["findings"]}


def test_the_converted_document_is_read_back_after_import(tmp_path):
    google = ReadingGoogle(docs_document([paragraph(text("Hello\n"))]), build_pdf([TEXT]))
    report = job_with(tmp_path, para(), google, pages=1)

    assert google.read == [("document", "file-1"), ("pdf", "file-1")]
    back = report["readBack"]
    assert back["checked"] == ["document", "pdf"]
    assert back["findings"] == []
    assert back["pdf"] == {"pages": 1, "probablyBlank": []}
    assert back["source"] == {"pages": 1, "tables": 0}


def test_pictures_still_floating_are_counted(tmp_path):
    google = ReadingGoogle(
        docs_document([paragraph(text("\n"))], positioned=3, inline=2), build_pdf([TEXT])
    )
    report = job_with(tmp_path, para(), google)

    assert codes(report)["pictures_still_floating"]["count"] == 3
    assert report["readBack"]["document"]["inlineObjects"] == 2


def test_a_table_lost_in_import_is_reported(tmp_path):
    google = ReadingGoogle(docs_document([paragraph(text("\n"))]), build_pdf([TEXT]))
    report = job_with(tmp_path, question_table(rows=1), google)

    found = codes(report)["table_count_changed"]
    assert (found["source"], found["converted"]) == (1, 0)


def test_blank_pages_and_page_break_paragraphs_are_reported_with_their_pages(tmp_path):
    content = [
        paragraph(text("Sheet one\n")),
        paragraph(PAGE_BREAK, text("\n")),
        paragraph(text("Sheet two\n")),
    ]
    google = ReadingGoogle(docs_document(content), build_pdf([TEXT, BLANK, TEXT]))
    report = job_with(tmp_path, para(), google, pages=2)

    found = codes(report)
    assert found["pages_probably_blank"]["pages"] == [2]
    assert found["page_break_paragraphs"]["count"] == 1
    assert (found["page_count_changed"]["source"], found["page_count_changed"]["converted"]) == (
        2,
        3,
    )


def test_the_findings_stay_off_screen_and_carry_no_document_text(tmp_path):
    content = [paragraph(text(SECRET + "\n")), paragraph(PAGE_BREAK, text("\n"))]
    google = ReadingGoogle(docs_document(content, positioned=1), build_pdf([TEXT, BLANK]))
    report = job_with(tmp_path, para(), google)

    # The findings exist, in the report...
    assert set(codes(report)) >= {"pictures_still_floating", "pages_probably_blank"}

    # The screen shows `warnings`; nothing from the read-back goes there.
    assert not any(
        w["code"].startswith(("pictures_still", "pages_probably")) for w in report["warnings"]
    )
    assert SECRET not in json.dumps(report)
    assert "Question 1" not in json.dumps(report)


def test_a_read_back_that_fails_leaves_the_conversion_as_it_was(tmp_path):
    google = ReadingGoogle(docs_document([paragraph(text("\n"))]), build_pdf([TEXT]), fail="pdf")
    report = job_with(tmp_path, para(), google)

    assert report["status"] == "completed_with_warnings"
    assert report["verification"] == "text_checked"
    back = report["readBack"]
    assert back["checked"] == ["document"]
    assert back["unavailable"] == {"pdf": "export_too_large"}


def test_an_unreadable_pdf_is_reported_as_unreadable_not_as_zero_pages(tmp_path):
    google = ReadingGoogle(docs_document([paragraph(text("\n"))]), b"not a pdf")
    report = job_with(tmp_path, para(), google, pages=1)

    back = report["readBack"]
    assert back["checked"] == ["document"]
    assert back["unavailable"] == {"pdf": "unreadable"}
    assert "page_count_changed" not in codes(report)


# ------------------------------------------------- the two Google reads


def google_answering(handler):
    return Google("token", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_the_document_is_read_with_every_tab():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json={"documentId": "doc"})

    answer = asyncio.run(google_answering(handler).document("doc"))
    assert answer == {"documentId": "doc"}
    assert seen[0].path == "/v1/documents/doc"
    assert seen[0].params["includeTabsContent"] == "true"


def test_a_pdf_export_larger_than_the_limit_is_not_held():
    def handler(request):
        assert request.url.params["mimeType"] == "application/pdf"
        return httpx.Response(200, content=b"%PDF-" + b"x" * 5000)

    google = google_answering(handler)
    assert asyncio.run(google.export_pdf("doc", max_bytes=10000)).startswith(b"%PDF-")
    try:
        asyncio.run(google.export_pdf("doc", max_bytes=1000))
    except ToolkitError as exc:
        assert exc.detail == "export_too_large"
    else:
        raise AssertionError("an export over the limit was accepted")
