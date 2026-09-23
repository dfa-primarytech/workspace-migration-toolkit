import asyncio
import json
import zipfile
from collections import Counter

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.docs import Ids, render, send_behind_text, transform
from workspace_toolkit.docx import NS, local, parse, q
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
        f"<wp:docPr/>"
        f"{body}"
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
# A picture as Word actually writes one. The short form this used to carry --
# uri="pic" wrapping a bare <a:blip> -- is not renderable DrawingML, so every
# picture test passed against a shape no reader would draw.
PICTURE = (
    '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="Picture"/><pic:cNvPicPr/></pic:nvPicPr>'
    '<pic:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
    '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="3000000" cy="1000000"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
    "</a:graphicData></a:graphic>"
)
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
    with pytest.raises(ToolkitError) as excinfo:
        resolve("budget.xlsx")
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

    def __init__(self, exported="Card text", importable=True, refuse_assets=False):
        self.exported = exported
        self.importable = importable
        self.refuse_assets = refuse_assets
        self.uploads = []

    async def request(self, method, url, **kwargs):
        from workspace_toolkit.google import DOCS_MIME
        from workspace_toolkit.package import DOCX_MIME

        return {"importFormats": {DOCX_MIME: [DOCS_MIME]} if self.importable else {}}

    async def folder(self, job_name="Conversion"):
        return "folder-id"

    async def upload(self, path, name, mime, parent, convert=False, target=None, retry=False):
        if retry and self.refuse_assets:
            # `retry=True` marks the private asset copies, never the document.
            from workspace_toolkit.errors import ToolkitError

            raise ToolkitError("upload_uncertain", "refused", 502, detail="http_429")
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

    report = asyncio.run(convert(root, manifest, google, original_name="Worksheet"))
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
    saved = [u["name"] for u in google.uploads[1:-1]]
    # Named after the document, with a suffix, rather than left as a digest. A
    # document gets no page number: nothing in its manifest links a picture to
    # one, and its "pages" are section breaks rather than printed pages.
    assert saved == ["Worksheet – image 1.png"], saved
    assert report["assetOutputs"][0]["kind"] == "image"
    assert report["assetOutputs"][0]["name"] == "Worksheet – image 1.png"
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
        "picturesInlined": 0,
        "tablesNarrowed": 0,
        "picturesShrunk": 0,
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


def test_an_empty_text_box_produces_no_table(tmp_path):
    """Found in a real worksheet: four boxes of a quarter-inch square, empty.

    Word leaves these behind while a document is edited. Converting one gives
    a floating table wrapping an empty cell, plus the empty paragraphs that
    keep tables apart -- clutter that takes up space on the page and can
    displace what is around it, in exchange for nothing, because there is no
    text to make editable.
    """
    empty = TEXTBOX.replace("<w:p><w:r><w:t>Card text</w:t></w:r></w:p>", "")
    root, report = transform_body(
        tmp_path, anchor(empty, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION
    )
    assert report["textboxes"] == 0
    assert root.find(".//" + q("w", "tbl")) is None


def test_a_box_holding_only_a_picture_is_still_converted(tmp_path):
    """The emptiness test must not discard content that simply is not text."""
    with_picture = TEXTBOX.replace(
        "<w:p><w:r><w:t>Card text</w:t></w:r></w:p>",
        '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="100" cy="100"/>'
        '<a:graphic><a:graphicData uri="pic"><a:blip r:embed="rId1"/>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>",
    )
    root, report = transform_body(
        tmp_path,
        anchor(with_picture, h=("column", offset(0)), v=("paragraph", offset(0))) + SECTION,
    )
    assert report["textboxes"] == 1, "a box holding a picture was treated as empty"
    assert root.find(".//" + q("w", "tbl")) is not None


def test_a_refused_asset_copy_still_leaves_the_document_verified(tmp_path):
    """The private asset copies are a fallback, not the deliverable.

    Measured on a real worksheet: 27 of 65 copies uploaded, the 28th was
    refused, and that one refusal abandoned the other 37 *and* skipped the
    document's own verification -- reporting a good conversion as failed.
    """
    body = anchor(PICTURE) + SECTION
    report, google = converted_job(tmp_path, body, refuse_assets=True)

    assert report["status"] == "completed_with_warnings", "the document itself uploaded fine"
    assert report["verification"] == "text_checked", "verification must not be skipped"
    assert report["documentId"], "the document is still the deliverable"

    incomplete = [w for w in report["warnings"] if w["code"] == "asset_copies_incomplete"]
    assert incomplete, "a person should still be told the copies are missing"
    assert incomplete[0]["saved"] == 0
    assert incomplete[0]["attempted"] >= 1
    assert incomplete[0]["reasons"] == ["http_429"], "the report should say which way it failed"
    assert google.uploads[-1]["name"] == "Conversion report.json", "the report is still saved"


def in_cell(inner):
    """One table with a single cell holding `inner`."""
    return (
        "<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w='5000'/></w:tblGrid>"
        f"<w:tr><w:tc><w:tcPr/>{inner}</w:tc></w:tr></w:tbl>"
    )


def transformed(tmp_path, body):
    root = parse_xml(document(body))
    report = transform(root)
    return root, report


# A4 is 11906 twips wide. With 1440 twip margins, 9026 are printable.
A4_SECTION = (
    "<w:p><w:pPr><w:sectPr>"
    '<w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:left="1440" w:right="1440" w:top="1440" w:bottom="1440"/>'
    "</w:sectPr></w:pPr></w:p>"
)


def wide_table(inner="", columns=(6000, 6000)):
    grid = "".join(f"<w:gridCol w:w='{w}'/>" for w in columns)
    # `inner` goes in the first cell only, so counts are not silently doubled.
    cells = "".join(
        f"<w:tc><w:tcPr><w:tcW w:w='{w}' w:type='dxa'/></w:tcPr>{inner if n == 0 else ''}</w:tc>"
        for n, w in enumerate(columns)
    )
    return f"<w:tbl><w:tblPr/><w:tblGrid>{grid}</w:tblGrid><w:tr>{cells}</w:tr></w:tbl>"


def parse_xml(text):
    from defusedxml.ElementTree import fromstring

    return fromstring(text)


def test_a_picture_floating_inside_a_cell_becomes_cell_content(tmp_path):
    """A floating picture is positioned against the page, never its cell.

    So the row stays as short as its text and the picture is drawn across the
    borders. Inline content contributes to the cell's height instead.
    """
    body = in_cell(anchor(PICTURE, h=("column", offset(0)), v=("paragraph", offset(0)))) + SECTION
    root, report = transformed(tmp_path, body)

    assert root.find(".//" + q("wp", "anchor")) is None, "it must stop floating"
    inline = root.find(".//" + q("wp", "inline"))
    assert inline is not None, "it should become inline cell content"
    assert report["picturesInlined"] == 1

    # The picture itself must survive intact, not be rebuilt from guesses.
    assert inline.find(".//" + q("a", "blip")).get(q("r", "embed")) == "rId1"
    assert inline.find(q("wp", "extent")).get("cx") == "3000000"

    names = [local(child.tag) for child in inline]
    assert names == sorted(names, key=["extent", "effectExtent", "docPr", "graphic"].index), names


def test_a_picture_floating_outside_any_cell_is_left_alone(tmp_path):
    """A logo in a letterhead belongs where its author put it.

    Recovering which cell an image *visually* sits in, when the anchor says
    otherwise, needs geometry. Guessing is worse than leaving it.
    """
    body = anchor(PICTURE, h=("page", offset(0)), v=("page", offset(0))) + SECTION
    root, report = transformed(tmp_path, body)

    assert root.find(".//" + q("wp", "anchor")) is not None, "it should still float"
    assert root.find(".//" + q("wp", "inline")) is None
    assert report["picturesInlined"] == 0


def test_a_picture_sent_behind_the_text_stays_floating(tmp_path):
    """A backdrop is deliberate. Inlining it would push the text down a page."""
    body = in_cell(anchor(PICTURE, behind="1", h=("page", offset(0)))) + SECTION
    root, report = transformed(tmp_path, body)

    assert root.find(".//" + q("wp", "anchor")) is not None
    assert report["picturesInlined"] == 0


def widths(root):
    return [int(c.get(q("w", "w"))) for c in root.iter(q("w", "gridCol"))]


def test_a_table_wider_than_the_paper_is_brought_within_the_margins():
    """Word lets a table state more columns than the page can hold.

    Measured on a real worksheet: about 575pt of columns in about 523pt of
    printable width, so every row crossed the right margin whatever the
    images did.
    """
    root = parse_xml(document(wide_table() + A4_SECTION))
    report = transform(root)

    assert sum(widths(root)) <= 9026, "the table must fit between the margins"
    assert widths(root) == [4513, 4513], "columns keep their proportions"
    assert report["tablesNarrowed"] == 1

    stated = [int(c.get(q("w", "w"))) for c in root.iter(q("w", "tcW"))]
    assert stated == [4513, 4513], "the cells must agree with the grid they sit in"


def test_a_table_that_already_fits_is_left_exactly_as_it_was():
    root = parse_xml(document(wide_table(columns=(4000, 4000)) + A4_SECTION))
    report = transform(root)

    assert widths(root) == [4000, 4000], "nothing to fix means nothing to change"
    assert report["tablesNarrowed"] == 0


def test_a_picture_comes_down_with_the_column_that_holds_it():
    """A picture sized for the old column would overflow the narrowed one."""
    # Built here rather than from PICTURE: this needs the <a:ext> geometry a
    # real picture carries, so the outer frame and inner shape can be compared.
    picture = (
        "<w:p><w:r><w:drawing><wp:inline>"
        "<wp:extent cx='3810000' cy='1905000'/><wp:docPr/>"
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic><pic:blipFill><a:blip r:embed='rId1'/></pic:blipFill>"
        "<pic:spPr><a:xfrm><a:ext cx='3810000' cy='1905000'/></a:xfrm></pic:spPr></pic:pic>"
        "</a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )
    root = parse_xml(document(wide_table(picture) + A4_SECTION))
    report = transform(root)

    extent = root.find(".//" + q("wp", "extent"))
    column = widths(root)[0]
    limit = (column - 216) * 635  # both default cell margins
    assert int(extent.get("cx")) <= limit, "the picture must fit its cell"
    assert report["picturesShrunk"] == 1

    # Shape is preserved: the inner geometry moves with the outer frame.
    assert int(extent.get("cy")) < 1905000
    inner = root.find(".//" + q("a", "ext"))
    assert int(inner.get("cx")) == int(extent.get("cx")), "frame and geometry must agree"


def test_a_nested_table_is_measured_against_its_cell_not_the_page():
    """A nested table is bounded by its cell. Shrinking it against the page
    would compound with the shrink its parent already took."""
    inner = wide_table(columns=(6000, 6000))
    root = parse_xml(document(wide_table(inner) + A4_SECTION))
    report = transform(root)

    assert report["tablesNarrowed"] == 1, "only the outer table is measured"
    assert widths(root)[2:] == [6000, 6000], "the nested grid is left alone"


def inline_picture(cx, cy):
    return (
        "<w:p><w:r><w:drawing><wp:inline>"
        f"<wp:extent cx='{cx}' cy='{cy}'/><wp:docPr/>"
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f"<pic:pic><pic:spPr><a:xfrm><a:ext cx='{cx}' cy='{cy}'/></a:xfrm></pic:spPr></pic:pic>"
        "</a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def test_a_tracked_page_setup_change_is_measured_by_the_current_page():
    """w:sectPrChange keeps the previous properties inside the current ones,
    after them in document order. Measuring those would use the old page."""
    body_section = (
        "<w:sectPr><w:pgSz w:w='11906' w:h='16838'/>"
        "<w:pgMar w:left='1440' w:right='1440' w:top='1440' w:bottom='1440'/>"
        "<w:sectPrChange w:id='1' w:author='a'><w:sectPr>"
        "<w:pgSz w:w='16838' w:h='11906'/>"
        "<w:pgMar w:left='720' w:right='720' w:top='720' w:bottom='720'/>"
        "</w:sectPr></w:sectPrChange></w:sectPr>"
    )
    root = parse_xml(document(wide_table() + body_section))
    report = transform(root)

    assert report["tablesNarrowed"] == 1
    assert sum(widths(root)) <= 9026, "measured against the current A4 page, not the old one"


def test_the_tables_own_stated_width_is_narrowed_with_its_grid():
    table = wide_table().replace(
        "<w:tblPr/>", "<w:tblPr><w:tblW w:w='12000' w:type='dxa'/></w:tblPr>"
    )
    root = parse_xml(document(table + A4_SECTION))
    transform(root)

    stated = int(root.find(".//" + q("w", "tblW")).get(q("w", "w")))
    assert stated == sum(widths(root)), "the table must not claim a width its grid no longer has"


def test_a_nested_tables_cells_keep_the_widths_its_grid_still_has():
    inner = wide_table(columns=(6000, 6000))
    root = parse_xml(document(wide_table(inner) + A4_SECTION))
    transform(root)

    nested = root.findall(".//" + q("w", "tbl"))[1]
    cells = [int(w.get(q("w", "w"))) for w in nested.iter(q("w", "tcW"))]
    assert cells == [6000, 6000], "nested cells must still agree with their untouched grid"


def test_a_picture_in_a_merged_cell_is_measured_by_every_column_it_spans():
    # The picture fits the two narrowed columns together, so it must not shrink.
    table = (
        "<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w='6000'/><w:gridCol w:w='6000'/></w:tblGrid>"
        f"<w:tr><w:tc><w:tcPr><w:gridSpan w:val='2'/></w:tcPr>{inline_picture(4500000, 2250000)}"
        "</w:tc></w:tr>"
        "<w:tr><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>"
    )
    root = parse_xml(document(table + A4_SECTION))
    report = transform(root)

    assert report["tablesNarrowed"] == 1
    assert int(root.find(".//" + q("wp", "extent")).get("cx")) == 4500000
    assert report["picturesShrunk"] == 0


def test_a_cell_that_cannot_be_placed_on_the_grid_keeps_its_picture():
    # Three cells over a two-column grid: the third has no column to measure.
    # Big enough that shrinking it against a guessed width would show.
    table = (
        "<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w='6000'/><w:gridCol w:w='6000'/></w:tblGrid>"
        "<w:tr><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc>"
        f"<w:tc>{inline_picture(5000000, 2500000)}</w:tc></w:tr></w:tbl>"
    )
    root = parse_xml(document(table + A4_SECTION))
    report = transform(root)

    assert int(root.find(".//" + q("wp", "extent")).get("cx")) == 5000000
    assert report["picturesShrunk"] == 0
