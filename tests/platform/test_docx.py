import asyncio
import json
import zipfile
from collections import Counter

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.docs import Ids, render, send_behind_text, transform
from workspace_toolkit.docx import NS, parse, q
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.package import CONTENT_NS, DOCX, DOCX_MAIN_MIME, REL_NS, Package

GROUP_URI = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
CHART_URI = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"

XMLNS = " ".join(f'xmlns:{p}="{u}"' for p, u in NS.items())


def run(body, *, h=None, v=None, cx=3000000, cy=1000000, dist="", behind="0"):
    position = ""
    for axis, spec in (("H", h), ("V", v)):
        if spec is None:
            continue
        frame, inner = spec
        position += f'<wp:position{axis} relativeFrom="{frame}">{inner}</wp:position{axis}>'
    return (
        f'<w:r><w:drawing><wp:anchor behindDoc="{behind}" {dist}>'
        f"{position}"
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f"{body}"
        f"<wp:docPr/>"
        f"</wp:anchor></w:drawing></w:r>"
    )


def para(*runs):
    return "<w:p>" + "".join(runs) + "</w:p>"


def anchor(*args, **kwargs):
    """One anchor in its own paragraph -- the common case."""
    return para(run(*args, **kwargs))


def offset(value):
    return f"<wp:posOffset>{value}</wp:posOffset>"


def align(keyword):
    return f"<wp:align>{keyword}</wp:align>"


TEXTBOX = (
    '<a:graphic><a:graphicData uri="x"><wps:wsp><wps:spPr>'
    '<a:solidFill><a:srgbClr val="FFE599"/></a:solidFill></wps:spPr>'
    "<wps:txbx><w:txbxContent><w:p><w:r><w:t>Card text</w:t></w:r></w:p></w:txbxContent>"
    "</wps:txbx></wps:wsp></a:graphicData></a:graphic>"
)
PICTURE = '<a:graphic><a:graphicData uri="pic"><a:blip r:embed="rId1"/></a:graphicData></a:graphic>'
INK = "<w14:contentPart/>"


def graphic(uri):
    return f'<a:graphic><a:graphicData uri="{uri}"/></a:graphic>'


def document(body):
    return f"<w:document {XMLNS}><w:body>{body}</w:body></w:document>"


SECTION = '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr></w:p>'


def docx_parts(body):
    return {
        "[Content_Types].xml": (
            f'<Types xmlns="{CONTENT_NS}">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            f'<Override PartName="/word/document.xml" ContentType="{DOCX_MAIN_MIME}"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{REL_NS}"><Relationship Id="root" '
            f'Type="{NS["r"]}/officeDocument" Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": document(body),
        "word/media/image1.png": b"\x89PNG\r\n\x1a\nfixture",
    }


def write_docx(path, body):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in docx_parts(body).items():
            archive.writestr(name, content)
    return path


def open_package(tmp_path, body, name="sample.docx"):
    return Package(write_docx(tmp_path / name, body), Settings(), DOCX)


def parse_body(tmp_path, body):
    package = open_package(tmp_path, body)
    try:
        return parse(package, "sample.docx", "sha")
    finally:
        package.close()


def transform_body(tmp_path, body):
    package = open_package(tmp_path, body)
    try:
        root = package.xml(DOCX.main_part)
        report = transform(root, Ids())
        return root, report
    finally:
        package.close()


# ---------------------------------------------------------------- parser


def test_package_rejects_a_pptx_shaped_file(tmp_path):
    path = tmp_path / "wrong.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", f'<Types xmlns="{CONTENT_NS}"/>')
        archive.writestr("ppt/presentation.xml", "<p/>")
    with pytest.raises(ToolkitError) as excinfo:
        Package(path, Settings(), DOCX)
    assert excinfo.value.code == "invalid_package"


def test_anchors_are_classified_and_never_silently_unknown(tmp_path):
    body = (
        anchor(TEXTBOX, h=("column", offset(-457200)), v=("paragraph", offset(914400)))
        + anchor(PICTURE, h=("page", offset(0)), v=("page", offset(0)))
        + anchor(INK)
        + anchor(graphic(GROUP_URI))
        + anchor(graphic(CHART_URI))
        + anchor(graphic(DIAGRAM_URI))
        + SECTION
    )
    manifest = parse_body(tmp_path, body)
    elements = manifest["pages"][0]["elements"]
    assert [e["kind"] for e in elements] == [
        "textbox",
        "picture",
        "ink",
        "unsupported",
        "unsupported",
        "unsupported",
    ]
    assert [e["label"] for e in elements[3:]] == ["grouped shape", "chart", "SmartArt diagram"]
    assert [e["type"] for e in elements[:3]] == ["text", "image", "shape"]


def test_a_smartart_fallback_picture_is_not_mistaken_for_a_picture(tmp_path):
    # SmartArt commonly carries a fallback <a:blip>. Without an explicit entry
    # it would classify as a picture and could be dropped as a backing image.
    body = (
        f'<w:p><w:r><w:drawing><wp:anchor><wp:extent cx="1" cy="1"/>'
        f'<a:graphic><a:graphicData uri="{DIAGRAM_URI}"><a:blip r:embed="rId9"/>'
        f"</a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p>" + SECTION
    )
    manifest = parse_body(tmp_path, body)
    element = manifest["pages"][0]["elements"][0]
    assert element["kind"] == "unsupported"
    assert element["compatibility"] == "UNSUPPORTED"


def test_bounds_and_page_size_are_reported_in_points(tmp_path):
    body = anchor(TEXTBOX, h=("column", offset(914400)), v=("paragraph", offset(457200))) + SECTION
    manifest = parse_body(tmp_path, body)
    page = manifest["pages"][0]
    assert page["widthPt"] == pytest.approx(595.3)
    assert page["heightPt"] == pytest.approx(841.9)
    box = page["elements"][0]["bounds"]
    assert box["x"] == 72 and box["y"] == 36
    assert box["width"] == pytest.approx(236.22, abs=0.01)
    assert box["height"] == pytest.approx(78.74, abs=0.01)


def test_an_unpositioned_text_box_is_flagged_not_dropped(tmp_path):
    manifest = parse_body(tmp_path, anchor(TEXTBOX) + SECTION)
    element = manifest["pages"][0]["elements"][0]
    assert element["bounds"]["x"] is None
    assert {w["code"] for w in element["warnings"]} == {"textbox_unpositioned"}


def test_elements_are_assigned_to_their_section(tmp_path):
    body = anchor(PICTURE) + SECTION + anchor(PICTURE) + SECTION
    manifest = parse_body(tmp_path, body)
    assert manifest["document"]["pageCount"] == 2
    assert [len(p["elements"]) for p in manifest["pages"]] == [1, 1]


# ---------------------------------------------------------------- renderer


def test_a_text_box_becomes_a_table_positioned_where_it_was(tmp_path):
    body = anchor(TEXTBOX, h=("column", offset(-457200)), v=("paragraph", offset(914400))) + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["textboxes"] == 1
    table = root.find(".//" + q("w", "tbl"))
    assert table is not None
    position = table.find(q("w", "tblPr") + "/" + q("w", "tblpPr"))
    assert position.get(q("w", "tblpX")) == "-720"
    assert position.get(q("w", "tblpY")) == "1440"
    assert position.get(q("w", "horzAnchor")) == "text"
    assert position.get(q("w", "vertAnchor")) == "text"
    # The text survives, still editable, inside the cell.
    assert table.find(".//" + q("w", "t")).text == "Card text"
    # And the shape's fill becomes cell shading.
    assert table.find(".//" + q("w", "shd")).get(q("w", "fill")) == "FFE599"


def test_schema_order_inside_tblPr_is_respected(tmp_path):
    body = anchor(TEXTBOX, h=("margin", align("center")), v=("paragraph", offset(0))) + SECTION
    root, _ = transform_body(tmp_path, body)
    names = [c.tag.rsplit("}", 1)[-1] for c in root.find(".//" + q("w", "tblPr"))]
    assert names[:3] == ["tblpPr", "tblOverlap", "tblW"]


def test_align_keywords_become_specs_not_coordinates(tmp_path):
    body = anchor(TEXTBOX, h=("margin", align("right")), v=("page", align("top"))) + SECTION
    root, _ = transform_body(tmp_path, body)
    position = root.find(".//" + q("w", "tblpPr"))
    assert position.get(q("w", "tblpXSpec")) == "right"
    assert position.get(q("w", "tblpYSpec")) == "top"
    assert position.get(q("w", "tblpX")) is None
    assert position.get(q("w", "horzAnchor")) == "margin"


def test_a_positionless_text_box_yields_an_inline_table(tmp_path):
    root, _ = transform_body(tmp_path, anchor(TEXTBOX) + SECTION)
    table = root.find(".//" + q("w", "tbl"))
    assert table is not None
    assert table.find(q("w", "tblPr") + "/" + q("w", "tblpPr")) is None


def test_wrap_gaps_come_from_the_anchor_defaulting_to_180(tmp_path):
    body = (
        anchor(
            TEXTBOX,
            h=("column", offset(0)),
            v=("paragraph", offset(0)),
            dist='distL="228600"',
        )
        + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    position = root.find(".//" + q("w", "tblpPr"))
    assert position.get(q("w", "leftFromText")) == "360"
    assert position.get(q("w", "rightFromText")) == "180"


def test_each_text_box_gets_its_own_table_never_a_merged_row(tmp_path):
    same = dict(v=("paragraph", offset(0)))
    body = (
        anchor(TEXTBOX, h=("column", offset(-457200)), **same)
        + anchor(TEXTBOX, h=("column", offset(3000000)), **same)
        + SECTION
    )
    root, report = transform_body(tmp_path, body)
    tables = root.findall(".//" + q("w", "tbl"))
    assert report["textboxes"] == 2
    assert len(tables) == 2
    for table in tables:
        assert len(table.findall(".//" + q("w", "tc"))) == 1


def test_a_backing_picture_is_kept_and_pushed_behind_the_text(tmp_path):
    # Word anchors a card's text box and its artwork to the same paragraph.
    # Coincidence is only meaningful there: vertical offsets are
    # paragraph-relative, so comparing them across paragraphs is nonsense.
    same = dict(h=("column", offset(100000)), v=("paragraph", offset(200000)))
    body = para(run(TEXTBOX, **same), run(PICTURE, **same)) + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["pictures"] == 1
    remaining = root.find(".//" + q("wp", "anchor"))
    assert remaining is not None, "the artwork must not be deleted"
    assert remaining.get("behindDoc") == "1"
    assert remaining.find(q("wp", "wrapNone")) is not None


def test_a_picture_elsewhere_is_left_exactly_as_it_was(tmp_path):
    body = (
        para(
            run(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0))),
            run(PICTURE, h=("column", offset(5000000)), v=("paragraph", offset(0))),
        )
        + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    picture = root.find(".//" + q("wp", "anchor"))
    assert picture.get("behindDoc") == "0"
    assert picture.find(q("wp", "wrapNone")) is None


def test_wrap_elements_are_replaced_in_place_before_docPr(tmp_path):
    from xml.etree.ElementTree import Element, SubElement  # nosec B405

    anchor_el = Element(q("wp", "anchor"))
    SubElement(anchor_el, q("wp", "wrapSquare"))
    SubElement(anchor_el, q("wp", "docPr"))
    send_behind_text(anchor_el)
    # CT_Anchor forbids a wrap element after docPr.
    assert [c.tag.rsplit("}", 1)[-1] for c in anchor_el] == ["wrapNone", "docPr"]


def test_ink_is_removed_and_unsupported_objects_are_kept(tmp_path):
    body = anchor(INK) + anchor(graphic(CHART_URI)) + anchor(graphic(GROUP_URI)) + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["ink"] == 1
    assert report["unsupported"] == {"chart": 1, "grouped shape": 1}
    assert len(root.findall(".//" + q("wp", "anchor"))) == 2, "unsupported must survive"


def test_fallback_branches_are_dropped_and_choice_promoted(tmp_path):
    body = (
        "<w:p><mc:AlternateContent>"
        "<mc:Choice Requires='wps'><w:r><w:t>kept</w:t></w:r></mc:Choice>"
        "<mc:Fallback><w:r><w:t>discarded</w:t></w:r></mc:Fallback>"
        "</mc:AlternateContent></w:p>" + SECTION
    )
    root, _ = transform_body(tmp_path, body)
    texts = [t.text for t in root.iter(q("w", "t"))]
    assert texts == ["kept"]
    assert root.find(".//" + q("mc", "AlternateContent")) is None


def test_the_section_properties_paragraph_is_never_removed(tmp_path):
    root, _ = transform_body(tmp_path, SECTION)
    assert root.find(".//" + q("w", "sectPr")) is not None, "page setup would be lost"


def test_render_writes_a_package_google_can_import(tmp_path):
    body = anchor(TEXTBOX, h=("column", offset(-457200)), v=("paragraph", offset(0))) + SECTION
    package = open_package(tmp_path, body)
    try:
        report = render(package, tmp_path / "out" / "converted.docx")
    finally:
        package.close()
    assert report["textboxes"] == 1

    out = tmp_path / "out" / "converted.docx"
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        document_xml = archive.read("word/document.xml").decode()
        # Media and every other part must survive the round trip untouched.
        assert archive.read("word/media/image1.png").startswith(b"\x89PNG")
    assert names == set(docx_parts(body))
    assert document_xml.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    assert "w:tblpPr" in document_xml, "conventional prefixes must be preserved"

    # The output must still open as a valid package through the same guards.
    again = Package(out, Settings(), DOCX)
    try:
        assert again.xml(DOCX.main_part) is not None
    finally:
        again.close()


# ---------------------------------------------------------------- pipeline


def test_pipeline_selection_is_driven_by_the_filename():
    from workspace_toolkit.pipelines import resolve

    assert resolve("term plan.docx").fmt.key == "docx"
    assert resolve("assembly.PPTX").fmt.key == "pptx"
    # Spreadsheets became supported when the XLSX pipeline landed; this
    # previously asserted they were not, which is how the capability change
    # announced itself.
    assert resolve("budget.xlsx").fmt.key == "xlsx"
    assert resolve("budget.xlsm").fmt.key == "xlsm"
    with pytest.raises(ToolkitError) as excinfo:
        resolve("newsletter.pub")
    assert excinfo.value.code == "unsupported_type"


def test_each_pipeline_uses_its_own_job_filename():
    from workspace_toolkit.pipelines import resolve

    assert resolve("a.docx").source_name == "source.docx"
    assert resolve("a.pptx").source_name == "source.pptx"


def test_preflight_produces_a_manifest_and_a_rendered_package(tmp_path):
    # Exercises the real subprocess path: analyse and render both happen in the
    # sandboxed worker, which never holds credentials.
    body = anchor(TEXTBOX, h=("column", offset(-457200)), v=("paragraph", offset(0))) + SECTION
    root = tmp_path / "job"
    root.mkdir()
    write_docx(root / "source.docx", body)

    from workspace_toolkit.jobs import preflight
    from workspace_toolkit.package import DOCX as DOCX_FORMAT

    manifest = asyncio.run(preflight(root, Settings(), DOCX_FORMAT))
    assert manifest["source"]["type"] == "docx"
    assert manifest["pages"][0]["elements"][0]["kind"] == "textbox"
    assert (root / "result" / "converted.docx").exists()

    render_report = json.loads((root / "result" / "render.json").read_text(encoding="utf-8"))
    assert render_report["textboxes"] == 1
    assert render_report["tokens"] == {"Card": 1, "text": 1}

    with zipfile.ZipFile(root / "result" / "converted.docx") as archive:
        assert "w:tblpPr" in archive.read("word/document.xml").decode()


def test_media_is_extracted_for_recovery(tmp_path):
    root = tmp_path / "job"
    root.mkdir()
    write_docx(root / "source.docx", anchor(PICTURE) + SECTION)
    from workspace_toolkit.docx import analyse

    manifest = analyse(root / "source.docx", root / "result", Settings())
    assets = list(manifest["assets"].values())
    assert [a["kind"] for a in assets] == ["image"]
    assert (root / "result" / assets[0]["path"]).read_bytes().startswith(b"\x89PNG")


# ---------------------------------------------------------------- conversion


class FakeGoogle:
    """Stands in for Drive. Records what would have been sent."""

    def __init__(self, exported="Card text", importable=True):
        self.exported = exported
        self.importable = importable
        self.uploads = []

    async def request(self, method, url, **kwargs):
        from workspace_toolkit.google import DOCS_MIME
        from workspace_toolkit.package import DOCX_MIME

        return {"importFormats": {DOCX_MIME: [DOCS_MIME]} if self.importable else {}}

    async def folder(self):
        return "folder-id"

    async def upload(self, path, name, mime, parent, convert=False, target=None):
        self.uploads.append(
            {"path": path, "name": name, "mime": mime, "convert": convert, "target": target}
        )
        return {"id": f"file-{len(self.uploads)}"}

    async def export_text(self, file_id):
        return self.exported


def converted_job(tmp_path, body, **kwargs):
    root = tmp_path / "job"
    root.mkdir()
    write_docx(root / "source.docx", body)
    manifest = asyncio.run(preflight_manifest(root))
    google = FakeGoogle(**kwargs)
    from workspace_toolkit.docs import convert

    report = asyncio.run(convert(root, manifest, google, output_name="Worksheet – converted"))
    return report, google


async def preflight_manifest(root):
    from workspace_toolkit.jobs import preflight
    from workspace_toolkit.package import DOCX as DOCX_FORMAT

    return await preflight(root, Settings(), DOCX_FORMAT)


def test_conversion_uploads_the_repaired_package_not_the_original(tmp_path):
    body = anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION
    report, google = converted_job(tmp_path, body)

    document = google.uploads[0]
    assert document["path"].name == "converted.docx", "the repairs are the whole point"
    assert document["convert"] is True
    assert document["target"] == "application/vnd.google-apps.document"
    assert report["url"].startswith("https://docs.google.com/document/d/")
    assert report["status"] == "completed_with_warnings"
    assert report["verification"] == "text_checked"


def test_missing_text_is_reported_as_a_count_never_as_content(tmp_path):
    # A distinctive canary so "did the document's own words leak into the
    # report?" has an unambiguous answer. The report is saved to Drive, so it
    # must carry counts only.
    canary = "Quokka-Marmalade-7781"
    box = TEXTBOX.replace("Card text", canary)
    body = anchor(box, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION
    report, _ = converted_job(tmp_path, body, exported="")
    mismatch = [w for w in report["warnings"] if w["code"] == "text_mismatch"]
    assert mismatch and mismatch[0]["missingTokenCount"] == 1
    assert canary not in json.dumps(report)


def test_layout_always_needs_a_human_even_when_text_matches(tmp_path):
    body = anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION
    report, _ = converted_job(tmp_path, body)
    assert not [w for w in report["warnings"] if w["code"] == "text_mismatch"]
    assert [w for w in report["warnings"] if w["code"] == "visual_review_required"]


def test_an_account_without_word_import_fails_before_uploading(tmp_path):
    body = anchor(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION
    report, google = converted_job(tmp_path, body, importable=False)
    assert google.uploads == []
    assert report["status"] == "failed"
    assert [w for w in report["warnings"] if w["code"] == "conversion_unavailable"]


def test_recovered_media_is_saved_alongside_the_document(tmp_path):
    body = anchor(PICTURE) + SECTION
    report, google = converted_job(tmp_path, body)
    assert [u["name"] for u in google.uploads[1:-1]], "assets should be uploaded"
    assert report["assetOutputs"][0]["kind"] == "image"
    assert google.uploads[-1]["name"] == "Conversion report.json"


def test_fallback_duplicates_are_not_counted_as_separate_objects(tmp_path):
    """Word writes a shape twice: mc:Choice and a legacy mc:Fallback.

    Counting both makes a text box's own fallback look like a separate picture
    sitting exactly beneath it -- indistinguishable from a real card layout.
    Measured on real worksheets: 6 of 18 anchors in one, 4 of 15 in another.
    """
    inner = run(TEXTBOX, h=("column", offset(0)), v=("paragraph", offset(0)))
    fallback = run(PICTURE, h=("column", offset(0)), v=("paragraph", offset(0)))
    body = (
        "<w:p><mc:AlternateContent>"
        f"<mc:Choice Requires='wps'>{inner}</mc:Choice>"
        f"<mc:Fallback>{fallback}</mc:Fallback>"
        "</mc:AlternateContent></w:p>" + SECTION
    )
    manifest = parse_body(tmp_path, body)
    kinds = [e["kind"] for e in manifest["pages"][0]["elements"]]
    assert kinds == ["textbox"], "the fallback restatement is not extra content"

    # And the renderer agrees: the fallback is discarded before anchors are read.
    root, report = transform_body(tmp_path, body)
    assert report == {
        "textboxes": 1,
        "pictures": 0,
        "ink": 0,
        "legacyPictures": 0,
        "unsupported": {},
    }


def test_parser_and_renderer_agree_on_what_is_in_the_document(tmp_path):
    # These two run over different trees (the parser never sees the transform),
    # so a disagreement means the manifest is describing a document the
    # renderer is not producing.
    body = (
        anchor(TEXTBOX, h=("column", offset(-457200)), v=("paragraph", offset(0)))
        + anchor(PICTURE, h=("column", offset(3000000)), v=("paragraph", offset(0)))
        + anchor(graphic(CHART_URI))
        + SECTION
    )
    manifest = parse_body(tmp_path, body)
    counted = Counter(e["kind"] for e in manifest["pages"][0]["elements"])
    _, report = transform_body(tmp_path, body)
    assert counted["textbox"] == report["textboxes"]
    assert counted["picture"] == report["pictures"]
    assert counted["unsupported"] == sum(report["unsupported"].values())


# ---------------------------------------------------------------- legacy VML


def pict(style, rid="rId1", alt=None, wrapper="r"):
    attr = f' alt="{alt}"' if alt else ""
    shape = f'<v:shape style="{style}"{attr}><v:imagedata r:id="{rid}"/></v:shape>'
    return f"<w:p><w:{wrapper}><w:pict>{shape}</w:pict></w:{wrapper}></w:p>"


def test_a_vml_only_picture_becomes_an_inline_drawing(tmp_path):
    # Google's importer ignores <w:pict> entirely, so without this the image
    # simply disappears from the converted document.
    body = pict("width:117.4pt;height:78.3pt", alt="Reward stamp") + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["legacyPictures"] == 1
    assert root.find(".//" + q("w", "pict")) is None

    extent = root.find(".//" + q("wp", "extent"))
    assert extent.get("cx") == str(round(117.4 * 12700))
    assert extent.get("cy") == str(round(78.3 * 12700))
    assert root.find(".//" + q("a", "blip")).get(q("r", "embed")) == "rId1"
    assert root.find(".//" + q("wp", "docPr")).get("name") == "Reward stamp"
    # Inline, not anchored: a VML shape's position is not recoverable.
    assert root.find(".//" + q("wp", "inline")) is not None


def test_vml_sizes_are_read_in_every_unit_word_writes(tmp_path):
    for style, cx in (
        ("width:1in;height:1in", 914400),
        ("width:2.54cm;height:1in", 914400),
        ("width:25.4mm;height:1in", 914400),
        ("width:96px;height:1in", 914400),
        ("width:6pc;height:1in", 914400),
    ):
        root, report = transform_body(tmp_path, pict(style) + SECTION)
        assert report["legacyPictures"] == 1, style
        assert root.find(".//" + q("wp", "extent")).get("cx") == str(cx), style


def test_an_unmeasurable_vml_picture_is_left_alone_not_deleted(tmp_path):
    body = pict("width:auto;height:auto") + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["legacyPictures"] == 0
    assert root.find(".//" + q("w", "pict")) is not None, "content must survive"


def test_a_pict_outside_a_run_is_not_rewritten(tmp_path):
    # <w:drawing> is not a legal child of <w:object>.
    body = pict("width:10pt;height:10pt", wrapper="object") + SECTION
    root, report = transform_body(tmp_path, body)
    assert report["legacyPictures"] == 0
    assert root.find(".//" + q("w", "pict")) is not None


def test_generated_drawing_ids_are_unique(tmp_path):
    body = pict("width:10pt;height:10pt") + pict("width:20pt;height:20pt", rid="rId2") + SECTION
    root, _ = transform_body(tmp_path, body)
    ids = [e.get("id") for e in root.iter(q("wp", "docPr"))]
    assert len(ids) == 2 and len(set(ids)) == 2


# ---------------------------------------------------------------- headers


def docx_with_header(path, body, header, footer=None):
    parts = dict(docx_parts(body))
    parts["word/header1.xml"] = document(header).replace("w:document", "w:hdr")
    if footer is not None:
        parts["word/footer1.xml"] = document(footer).replace("w:document", "w:ftr")
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>",
        '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.wordprocessingml.header+xml"/></Types>',
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def render_with_header(tmp_path, body, header, footer=None):
    source = docx_with_header(tmp_path / "sample.docx", body, header, footer)
    package = Package(source, Settings(), DOCX)
    try:
        report = render(package, tmp_path / "out.docx")
    finally:
        package.close()
    with zipfile.ZipFile(tmp_path / "out.docx") as archive:
        parts = {n: archive.read(n).decode() for n in archive.namelist() if n.endswith(".xml")}
    return report, parts


def test_headers_get_the_same_structural_passes_as_the_body(tmp_path):
    # Branded letterheads put their content in headers. Converting the body
    # while leaving the header broken is the worst of both worlds.
    header = anchor(TEXTBOX, h=("margin", offset(0)), v=("paragraph", offset(0)))
    report, parts = render_with_header(tmp_path, SECTION, header)
    assert report["parts"] == ["word/document.xml", "word/header1.xml"]
    assert report["textboxes"] == 1
    assert "<w:tbl>" in parts["word/header1.xml"]
    assert "tblpPr" in parts["word/header1.xml"]


def test_footers_are_transformed_too_and_counts_are_merged(tmp_path):
    header = pict("width:10pt;height:10pt")
    footer = anchor(INK)
    report, parts = render_with_header(tmp_path, SECTION, header, footer)
    assert set(report["parts"]) == {
        "word/document.xml",
        "word/header1.xml",
        "word/footer1.xml",
    }
    assert report["legacyPictures"] == 1
    assert report["ink"] == 1


def test_header_text_is_not_counted_for_verification(tmp_path):
    # Drive's plain-text export does not reliably include headers, so counting
    # their text would report a mismatch on every document that has one.
    body = "<w:p><w:r><w:t>Body words</w:t></w:r></w:p>" + SECTION
    header = "<w:p><w:r><w:t>Letterhead</w:t></w:r></w:p>"
    report, _ = render_with_header(tmp_path, body, header)
    assert report["tokens"] == {"Body": 1, "words": 1}


def test_every_other_part_survives_the_multi_part_rewrite(tmp_path):
    header = anchor(TEXTBOX, h=("margin", offset(0)), v=("paragraph", offset(0)))
    source = docx_with_header(tmp_path / "sample.docx", SECTION, header)
    package = Package(source, Settings(), DOCX)
    try:
        render(package, tmp_path / "out.docx")
        original = set(package.names)
    finally:
        package.close()
    with zipfile.ZipFile(tmp_path / "out.docx") as archive:
        assert set(archive.namelist()) == original
        assert archive.read("word/media/image1.png").startswith(b"\x89PNG")
