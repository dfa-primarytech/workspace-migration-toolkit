"""Generated OOXML workbooks for issue #51; no source documents are checked in."""

import asyncio
import json
import zipfile

import pytest
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.google import save_report
from workspace_toolkit.package import XLSM, XLSX
from workspace_toolkit.sheets import SHEETS_MIME, verify
from workspace_toolkit.sheets import convert as convert_only
from workspace_toolkit.xlsx import NS, analyse, analysis_report

from .test_web import configured, signed_client
from .test_xlsx import workbook_parts


async def convert(root, manifest, google):
    """Converts, then saves the report as web.py does once a pipeline returns."""
    report = await convert_only(root, manifest, google)
    await save_report(root, report, google)
    return report


def generated_workbook(path, *, chart_sheet=False):
    parts = workbook_parts(suffix=path.suffix)
    # A macro-enabled container does not necessarily contain VBA.
    parts.pop("xl/vbaProject.bin", None)
    if chart_sheet:
        parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
            "</sheets>", '<sheet name="Chart overview" sheetId="2" r:id="chartSheet"/></sheets>'
        )
        parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
            "</Relationships>",
            f'<Relationship Id="chartSheet" Type="{NS["r"]}/chartsheet" Target="chartsheets/sheet1.xml"/></Relationships>',
        )
        parts["xl/chartsheets/sheet1.xml"] = (
            f'<chartsheet xmlns="{NS["x"]}" xmlns:r="{NS["r"]}">'
            '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
            '<drawing r:id="drawing"/></chartsheet>'
        )
        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        parts["xl/chartsheets/_rels/sheet1.xml.rels"] = (
            f'<Relationships xmlns="{rel_ns}"><Relationship Id="drawing" '
            f'Type="{NS["r"]}/drawing" Target="../drawings/drawing1.xml"/></Relationships>'
        )
        parts["xl/drawings/drawing1.xml"] = (
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            f'xmlns:r="{NS["r"]}"><xdr:absoluteAnchor><xdr:pos x="0" y="0"/>'
            '<xdr:ext cx="6000000" cy="4000000"/><xdr:graphicFrame macro="">'
            '<xdr:nvGraphicFramePr><xdr:cNvPr id="2" name="Chart"/>'
            "<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>"
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="chart"/>'
            "</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/>"
            "</xdr:absoluteAnchor></xdr:wsDr>"
        )
        parts["xl/drawings/_rels/drawing1.xml.rels"] = (
            f'<Relationships xmlns="{rel_ns}"><Relationship Id="chart" '
            f'Type="{NS["r"]}/chart" Target="../charts/chart1.xml"/></Relationships>'
        )
        parts["xl/charts/chart1.xml"] = (
            '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            '<c:chart><c:plotArea><c:layout/><c:pieChart><c:varyColors val="1"/>'
            '<c:ser><c:idx val="0"/><c:order val="0"/><c:val><c:numRef>'
            "<c:f>'Class data'!$B$1</c:f>"
            '<c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="1"/>'
            '<c:pt idx="0"><c:v>3</c:v></c:pt></c:numCache>'
            "</c:numRef></c:val></c:ser></c:pieChart></c:plotArea></c:chart></c:chartSpace>"
        )
        overrides = {
            "xl/chartsheets/sheet1.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.chartsheet+xml",
            "xl/drawings/drawing1.xml": "application/vnd.openxmlformats-officedocument.drawing+xml",
            "xl/charts/chart1.xml": "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
        }
        parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
            "</Types>",
            "".join(
                f'<Override PartName="/{name}" ContentType="{mime}"/>'
                for name, mime in overrides.items()
            )
            + "</Types>",
        )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return path


class RecordingGoogle:
    def __init__(self, formats=None, sheets=None):
        self.formats = (
            formats if formats is not None else {XLSX.mime: [SHEETS_MIME], XLSM.mime: [SHEETS_MIME]}
        )
        self.sheets = (
            sheets
            if sheets is not None
            else [{"properties": {"title": "Class data", "sheetType": "GRID"}}]
        )
        self.uploads = []
        self.folders = []
        self.warnings = []

    async def folder(self, name="Conversion"):
        self.folders.append(name)
        return "folder"

    async def upload(self, path, name, mime, parent, **kwargs):
        # The old fake never opened the file and therefore missed the crash.
        self.uploads.append((path.name, name, mime, path.read_bytes(), kwargs))
        return {"id": "upload-" + str(len(self.uploads))}

    async def request(self, method, url, **kwargs):
        if url.endswith("/about"):
            return {"importFormats": self.formats}
        return {"sheets": self.sheets}


@pytest.mark.parametrize("suffix,fmt", [(".xlsx", XLSX), (".xlsm", XLSM)])
def test_native_import_uses_the_actual_worker_package_and_mime(tmp_path, suffix, fmt):
    source = generated_workbook(tmp_path / ("source" + suffix))
    manifest = analyse(source, tmp_path / "result")
    google = RecordingGoogle()
    report = asyncio.run(convert(tmp_path, manifest, google))

    assert report["status"] == "converted_with_review"
    assert report["original"]["id"] == "upload-1"
    package = google.uploads[1]
    assert package[0] == "converted" + suffix
    assert package[2] == fmt.mime
    assert package[3] == source.read_bytes()
    assert package[4] == {"convert": True, "target": SHEETS_MIME}


def test_a_clean_workbook_is_still_converted_with_review(tmp_path):
    """#123: nothing in the read-back checks formulas, formatting, charts or
    protection, so even a workbook with no findings at all is sent for a look.
    Plain "converted" is kept for stronger verification (docs/xlsx-migration.md)."""
    source = generated_workbook(tmp_path / "source.xlsx")
    # As if preflight found nothing at all (the shared fixture has formulas).
    manifest = {**analyse(source, tmp_path / "result"), "warnings": []}
    report = asyncio.run(convert(tmp_path, manifest, RecordingGoogle()))

    assert report["status"] == report["migrationTier"] == "converted_with_review"
    assert [w["code"] for w in report["warnings"]] == ["workbook_review_required"]


def test_chart_sheet_is_inventoried_and_preserved_with_a_review_warning(tmp_path):
    source = generated_workbook(tmp_path / "source.xlsx", chart_sheet=True)
    manifest = analyse(source, tmp_path / "result")
    report = analysis_report(manifest)

    assert manifest["document"]["sheetCount"] == 2
    assert manifest["sheets"][1]["sheetType"] == "chartsheet"
    assert report["featureCounts"]["chartSheets"] == 1
    assert report["migrationTier"] == "converted_with_review"
    finding = next(w for w in report["warnings"] if w["code"] == "chart_sheet_needs_review")
    assert finding["classification"] == "UNSUPPORTED"
    assert finding["sheetIndex"] == 1
    assert [sheet["index"] for sheet in manifest["sheets"]] == [0, 1]
    assert "Chart overview" not in json.dumps(report)
    assert (tmp_path / "result/converted.xlsx").read_bytes() == source.read_bytes()

    google = RecordingGoogle(
        sheets=[
            {"properties": {"title": "Class data", "sheetType": "GRID"}},
            {"properties": {"title": "Chart overview", "sheetType": "OBJECT"}},
        ]
    )
    converted = asyncio.run(convert(tmp_path, manifest, google))
    codes = {w["code"] for w in converted["warnings"]}
    assert converted["status"] == "converted_with_review"
    assert "chart_sheet_needs_review" in codes
    assert not {"sheet_type_changed", "sheet_count_changed", "sheet_name_changed"} & codes
    assert google.uploads[1][3] == source.read_bytes()
    # A matching sheet count is not proof that the chart itself survived.
    assert "chart_sheet_needs_review" in google.uploads[-1][3].decode()
    assert any(
        w["code"] == "sheet_count_changed" for w in verify(manifest, {"sheets": google.sheets[:1]})
    )


@pytest.mark.parametrize("available", [True, False])
def test_xlsm_import_capability_is_checked_for_its_own_mime(tmp_path, available):
    source = generated_workbook(tmp_path / "source.xlsm")
    manifest = analyse(source, tmp_path / "result")
    formats = {XLSM.mime: [SHEETS_MIME]} if available else {XLSX.mime: [SHEETS_MIME]}
    google = RecordingGoogle(formats=formats)
    report = asyncio.run(convert(tmp_path, manifest, google))

    if available:
        assert report["status"] == "converted_with_review"
        assert google.uploads[1][2] == XLSM.mime
    else:
        assert report["status"] == "failed_with_partial_outputs"
        assert any(w["code"] == "conversion_unavailable" for w in report["warnings"])
        assert report["original"]["id"] == "upload-1"
        assert report["reportUrl"]
        assert not any(upload[4].get("convert") for upload in google.uploads)


@pytest.mark.parametrize(
    "sheet_type,relationship,namespace,root_name,content_type,code,count",
    [
        (
            "dialogsheet",
            NS["r"] + "/dialogsheet",
            NS["x"],
            "dialogsheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.dialogsheet+xml",
            "dialog_sheet_needs_manual_migration",
            "dialogSheets",
        ),
        (
            "macrosheet",
            "http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet",
            "http://schemas.microsoft.com/office/excel/2006/main",
            "macrosheet",
            "application/vnd.ms-excel.macrosheet+xml",
            "macro_sheet_needs_manual_migration",
            "macroSheets",
        ),
        (
            "intlMacrosheet",
            "http://schemas.microsoft.com/office/2006/relationships/xlIntlMacrosheet",
            "http://schemas.microsoft.com/office/excel/2006/main",
            "macrosheet",
            "application/vnd.ms-excel.intlmacrosheet+xml",
            "macro_sheet_needs_manual_migration",
            "macroSheets",
        ),
    ],
)
def test_dialog_and_macro_sheets_are_archived_and_escalated(
    tmp_path, sheet_type, relationship, namespace, root_name, content_type, code, count
):
    source = tmp_path / "source.xlsm"
    parts = workbook_parts(suffix=".xlsm")
    parts.pop("xl/vbaProject.bin")
    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
        "</sheets>", '<sheet name="Special sheet" sheetId="2" r:id="special"/></sheets>'
    )
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        "</Relationships>",
        f'<Relationship Id="special" Type="{relationship}" Target="special/sheet1.xml"/></Relationships>',
    )
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>",
        f'<Override PartName="/xl/special/sheet1.xml" ContentType="{content_type}"/></Types>',
    )
    body = "<x:sheetData/>" if root_name == "macrosheet" else ""
    parts["xl/special/sheet1.xml"] = (
        f'<{root_name} xmlns="{namespace}" xmlns:x="{NS["x"]}">{body}</{root_name}>'
    )
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    manifest = analyse(source, tmp_path / "result")
    assert manifest["sheets"][1]["sheetType"] == sheet_type
    assert manifest["inventory"]["vbaProjects"] == 0
    assert manifest["inventory"][count] == 1
    assert analysis_report(manifest)["featureCounts"][count] == 1
    finding = next(w for w in manifest["warnings"] if w["code"] == code)
    assert finding["classification"] == "UNSUPPORTED"
    google = RecordingGoogle()
    report = asyncio.run(convert(tmp_path, manifest, google))
    assert report["status"] == "manual_migration_required"
    assert google.uploads[0][3] == source.read_bytes()
    assert not any(upload[4].get("convert") for upload in google.uploads)
    assert "Special sheet" not in json.dumps(report)


@pytest.mark.parametrize("defect", ["missing", "external", "wrong_root"])
def test_invalid_sheet_references_remain_errors(tmp_path, defect):
    source = generated_workbook(tmp_path / "source.xlsx", chart_sheet=True)
    with zipfile.ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    if defect == "missing":
        del parts["xl/chartsheets/sheet1.xml"]
    elif defect == "external":
        parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
            b'Target="chartsheets/sheet1.xml"',
            b'Target="https://example.com/chart" TargetMode="External"',
        )
    else:
        parts["xl/chartsheets/sheet1.xml"] = f'<worksheet xmlns="{NS["x"]}"/>'.encode()
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    with pytest.raises(ToolkitError) as error:
        analyse(source, tmp_path / "result")
    assert error.value.code == "invalid_workbook"


@pytest.mark.parametrize("suffix,fmt", [(".xlsx", XLSX), (".xlsm", XLSM)])
def test_web_conversion_accepts_the_current_pipeline_call(tmp_path, monkeypatch, suffix, fmt):
    from workspace_toolkit import web
    from workspace_toolkit.package import digest

    source = generated_workbook(tmp_path / ("source" + suffix))
    payload = source.read_bytes()
    google = RecordingGoogle()
    monkeypatch.setattr(web, "Google", lambda token, client: google)
    client = signed_client(configured())
    response = client.post(
        "/api/convert",
        content=payload,
        headers={
            "content-type": fmt.mime,
            "x-upload-filename": "Generated" + suffix,
            "x-source-sha256": digest(payload),
            "x-csrf-token": "test-csrf",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "converted_with_review"
    assert google.folders == ["Generated – converted"]
    assert google.uploads[1][1] == "Generated – converted"
