import asyncio
import json
import os
import time
import zipfile
from dataclasses import replace

import httpx
import pytest
from workspace_toolkit.batch import FileStatus, WorkbookJob, plan
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.google import Google
from workspace_toolkit.jobs import preflight, sweep_stale_workspaces
from workspace_toolkit.package import CONTENT_NS, REL_NS, XLSM, XLSX, Package
from workspace_toolkit.pipelines import resolve
from workspace_toolkit.sheets import SHEETS_MIME, convert
from workspace_toolkit.xlsx import GOOGLE_MAX_CELL_CHARS, NS, analyse, analysis_report


def workbook_parts(
    *,
    suffix=".xlsx",
    dimension="C5",
    long_text="",
    external_target=None,
    features=(),
):
    fmt = XLSM if suffix == ".xlsm" else XLSX
    overrides = [
        f'<Override PartName="/xl/workbook.xml" ContentType="{fmt.main_mime}"/>',
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>',
    ]
    parts = {
        "[Content_Types].xml": f'<Types xmlns="{CONTENT_NS}"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>{"".join(overrides)}</Types>',
        "_rels/.rels": f'<Relationships xmlns="{REL_NS}"><Relationship Id="root" Type="{NS["r"]}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<workbook xmlns="{NS["x"]}" xmlns:r="{NS["r"]}"><sheets><sheet name="Class data" sheetId="1" r:id="sheet"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{REL_NS}"><Relationship Id="sheet" Type="{NS["r"]}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{NS["x"]}"><dimension ref="A1:{dimension}"/><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>SUM(1,2)</f><v>3</v></c><c r="C1" t="e"><f>1/0</f><v>#DIV/0!</v></c></row></sheetData><mergeCells><mergeCell ref="A2:B2"/></mergeCells><conditionalFormatting sqref="A1"/><dataValidations count="1"><dataValidation sqref="A1"/></dataValidations></worksheet>',
        "xl/sharedStrings.xml": f'<sst xmlns="{NS["x"]}"><si><t>{long_text or "private classroom value"}</t></si></sst>',
    }
    if external_target:
        parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
            "</workbook>",
            '<externalReferences><externalReference r:id="external"/></externalReferences></workbook>',
        )
        parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
            "</Relationships>",
            f'<Relationship Id="external" Type="{NS["r"]}/externalLink" Target="externalLinks/externalLink1.xml"/></Relationships>',
        )
        parts["xl/externalLinks/externalLink1.xml"] = f'<externalLink xmlns="{NS["x"]}"/>'
        parts["xl/externalLinks/_rels/externalLink1.xml.rels"] = (
            f'<Relationships xmlns="{REL_NS}"><Relationship Id="path" Type="{NS["r"]}/externalLinkPath" Target="file:///{external_target}" TargetMode="External"/></Relationships>'
        )
    feature_parts = {
        "pivot": ("xl/pivotTables/pivotTable1.xml", "<pivot/>"),
        "query": ("xl/queryTables/queryTable1.xml", "<query/>"),
        "connections": ("xl/connections.xml", "<connections/>"),
        "forms": ("xl/ctrlProps/ctrlProp1.xml", "<control/>"),
        "activex": ("xl/activeX/activeX1.xml", "<control/>"),
        "embedded": ("xl/embeddings/object1.bin", b"embedded"),
        "chart": ("xl/charts/chart1.xml", "<chart/>"),
    }
    for feature in features:
        name, data = feature_parts[feature]
        parts[name] = data
    if suffix == ".xlsm":
        parts["xl/vbaProject.bin"] = b"VBA-private-source"
    return parts


def write_workbook(path, **kwargs):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in workbook_parts(suffix=path.suffix, **kwargs).items():
            archive.writestr(name, data)
    return path


def test_preflight_inventory_is_content_free_and_worker_copy_is_exact(tmp_path):
    source = write_workbook(tmp_path / "source.xlsx")
    output = tmp_path / "result"
    manifest = analyse(source, output)
    assert (
        manifest["inventory"]
        | {
            "sheetCount": 1,
            "formulaCells": 2,
            "errorCells": 1,
        }
        == manifest["inventory"]
    )
    assert manifest["sheets"][0]["populatedCells"] == 3
    assert manifest["sheets"][0]["mergedRanges"] == 1
    assert (output / "converted.xlsx").read_bytes() == source.read_bytes()
    serialised = json.dumps(manifest)
    assert "private classroom value" not in serialised
    assert "SUM(1,2)" not in serialised
    report = json.dumps(analysis_report(manifest))
    assert "Class data" not in report


def test_google_limits_and_unsupported_features_escalate(tmp_path):
    long_text = "".join(
        chr(0x400 + ((index * 7919) % 5000)) for index in range(GOOGLE_MAX_CELL_CHARS + 1)
    )
    source = write_workbook(
        tmp_path / "source.xlsm",
        dimension="XFD1000",
        long_text=long_text,
        features=("pivot", "query", "connections", "forms", "activex", "embedded", "chart"),
    )
    manifest = analyse(source, tmp_path / "result")
    codes = {finding["code"] for finding in manifest["warnings"]}
    assert {
        "google_cell_limit",
        "cell_text_limit",
        "pivot_tables_need_review",
        "queries_need_manual_migration",
        "connections_need_manual_migration",
        "forms_need_manual_migration",
        "activex_need_manual_migration",
        "embedded_objects_need_manual_migration",
        "vba_needs_manual_migration",
        "charts_need_review",
    } <= codes
    assert analysis_report(manifest)["migrationTier"] == "manual_migration_required"
    assert manifest["macros"][0]["byteLength"] == len(b"VBA-private-source")
    assert "VBA-private-source" not in json.dumps(manifest)


def test_column_limit_and_external_target_inventory_are_redacted(tmp_path):
    source = write_workbook(
        tmp_path / "source.xlsx", dimension="ZZZZ1", external_target="Other%20Class.xlsx"
    )
    manifest = analyse(source, tmp_path / "result")
    assert manifest["externalWorkbookTargets"] == ["Other Class.xlsx"]
    assert {item["code"] for item in manifest["warnings"]} >= {
        "google_column_limit",
        "external_workbook_links",
    }
    assert "Other Class.xlsx" not in json.dumps(analysis_report(manifest))


def test_encrypted_container_is_reported(tmp_path):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1encrypted")
    with pytest.raises(ToolkitError) as error:
        Package(source, Settings(), XLSX)
    assert error.value.code == "encrypted_package"


def test_pipeline_and_subprocess_worker(tmp_path):
    source = write_workbook(tmp_path / "sample.xlsx")
    root = tmp_path / "job"
    root.mkdir()
    (root / "source.xlsx").write_bytes(source.read_bytes())
    manifest = asyncio.run(preflight(root, replace(Settings(), parser_timeout=10), XLSX))
    assert manifest["document"]["sheetCount"] == 1
    assert (root / "result/converted.xlsx").read_bytes() == source.read_bytes()
    assert resolve("school.XLSX").destination == "Google Sheets"
    assert resolve("macros.xlsm").fmt is XLSM


def test_batch_dependencies_cycles_retry_and_drive_mapping():
    first = WorkbookJob("a", "A.xlsx", "a" * 64, ("B.xlsx",))
    second = WorkbookJob("b", "B.xlsx", "b" * 64, ("A.xlsx", "Missing.xlsx"))
    batch = plan([first, second])
    assert first.cyclic and second.cyclic
    assert second.unresolved_count == 1
    second.destination_id = "drive-b"
    assert batch.destination_links("a") == {"B.xlsx": "drive-b"}
    assert batch.summary() == {
        "workbooks": 2,
        "statuses": {FileStatus.READY: 2},
        "unresolvedLinks": 1,
        "cyclicWorkbooks": 2,
    }
    assert first.idempotency_key == "workbook:" + "a" * 64
    first.begin_attempt()
    assert first.attempt == 1 and first.status == FileStatus.RUNNING
    first.retry()
    first.begin_attempt()
    assert first.attempt == 2


def test_native_google_import_archives_original_and_reads_structure(tmp_path):
    root = tmp_path / "job"
    result = root / "result"
    result.mkdir(parents=True)
    source = write_workbook(root / "source.xlsx")
    manifest = analyse(source, result)
    uploads = []

    def handler(request):
        if request.url.path.endswith("/about"):
            return httpx.Response(200, json={"importFormats": {XLSX.mime: [SHEETS_MIME]}})
        if request.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"id": "folder"})
        if request.method == "POST" and request.url.path == "/upload/drive/v3/files":
            uploads.append(json.loads(request.content))
            return httpx.Response(
                200, headers={"Location": "https://www.googleapis.com/upload/session"}
            )
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "upload-" + str(len(uploads))})
        if request.url.host == "sheets.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "sheets": [
                        {
                            "properties": {
                                "title": "Class data",
                                "sheetType": "GRID",
                                "hidden": False,
                            }
                        }
                    ]
                },
            )
        raise AssertionError(str(request.url))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await convert(
                root, manifest, Google("token", client), output_name="Class data – converted"
            )

    report = asyncio.run(run())
    assert report["status"] == "converted_with_review"
    assert report["verification"] == "sheet_count_names_and_visibility_checked"
    assert report["original"]["policy"] == "archive"
    assert [item["mimeType"] for item in uploads[:2]] == [XLSX.mime, SHEETS_MIME]


def test_macro_workbook_is_archived_but_not_imported(tmp_path):
    root = tmp_path / "job"
    result = root / "result"
    result.mkdir(parents=True)
    source = write_workbook(root / "source.xlsm")
    manifest = analyse(source, result)

    class FakeGoogle:
        def __init__(self):
            self.uploads = []

        async def folder(self):
            return "folder"

        async def upload(self, path, name, mime, parent, **kwargs):
            self.uploads.append((path.name, mime, kwargs))
            return {"id": "saved" + str(len(self.uploads))}

        async def request(self, *args, **kwargs):
            raise AssertionError("manual migration must not call Google import")

    google = FakeGoogle()
    report = asyncio.run(convert(root, manifest, google))
    assert report["status"] == "manual_migration_required"
    assert google.uploads[0][0] == "source.xlsm"
    assert all(not kwargs.get("convert") for _, _, kwargs in google.uploads)


def test_stale_workspace_sweeper_only_removes_old_matching_directories(tmp_path):
    old = tmp_path / "wmt-old"
    fresh = tmp_path / "wmt-fresh"
    unrelated = tmp_path / "other"
    for path in (old, fresh, unrelated):
        path.mkdir()
    now = time.time()
    os.utime(old, (now - 1000, now - 1000))
    assert sweep_stale_workspaces(replace(Settings(), temp_dir=str(tmp_path)), 100, now) == 1
    assert not old.exists()
    assert fresh.exists() and unrelated.exists()
