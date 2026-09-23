"""Google Sheets native-import boundary.

No formula or VBA translation occurs here. Drive performs the ordinary XLSX
import. Structural read-back uses the Sheets API through the existing narrow
``drive.file`` grant and never places cell contents in logs or reports.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import ToolkitError
from .google import DRIVE
from .model import Compatibility as C
from .model import warning
from .package import XLSM, XLSX
from .xlsx import analysis_report, tier

SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets/"
ORIGINAL_POLICIES = {"archive", "delete_after_conversion"}


def verify(manifest: dict, spreadsheet: dict) -> list[dict]:
    findings: list[dict] = []
    converted = spreadsheet.get("sheets", [])
    source = manifest["sheets"]
    if len(converted) != len(source):
        findings.append(
            warning(
                "sheet_count_changed",
                "The number of worksheets changed during import.",
                sourceCount=len(source),
                convertedCount=len(converted),
                classification=C.UNSUPPORTED,
            )
        )
    for original, target in zip(source, converted, strict=False):
        properties = target.get("properties", {})
        if properties.get("sheetType", "GRID") != "GRID":
            findings.append(
                warning(
                    "sheet_type_changed",
                    "A worksheet did not import as an editable grid.",
                    sheetIndex=original["index"],
                    classification=C.UNSUPPORTED,
                )
            )
        if properties.get("title") != original["name"]:
            findings.append(
                warning(
                    "sheet_name_changed",
                    "A worksheet name changed during import.",
                    sheetIndex=original["index"],
                    classification=C.SUBSTITUTED,
                )
            )
        expected_hidden = original["state"] in {"hidden", "veryHidden"}
        if bool(properties.get("hidden", False)) != expected_hidden:
            findings.append(
                warning(
                    "sheet_visibility_changed",
                    "A worksheet's visibility changed during import.",
                    sheetIndex=original["index"],
                    classification=C.SUBSTITUTED,
                )
            )
    findings.append(
        warning(
            "workbook_review_required",
            "Review formulas, charts, formatting, validations and protected areas in the converted workbook. Cell contents were not read into the report.",
            classification=C.UNSUPPORTED,
        )
    )
    return findings


async def convert(
    root: Path,
    manifest: dict,
    google,
    progress: dict | None = None,
    output_name: str = "Converted workbook",
    original_policy: str = "archive",
    dependencies_resolved: bool = False,
) -> dict:
    if original_policy not in ORIGINAL_POLICIES:
        raise ValueError("Unknown original workbook policy")
    report = progress if progress is not None else {}
    report.update(analysis_report(manifest))
    report.update(status="converting", outputs=[], assetOutputs=[])
    fmt = XLSM if manifest["source"]["type"] == "xlsm" else XLSX
    try:
        folder = await google.folder()
        report["folderUrl"] = "https://drive.google.com/drive/folders/" + folder
        if original_policy == "archive":
            original = await google.upload(
                root / ("source" + fmt.suffix), "Original workbook" + fmt.suffix, fmt.mime, folder
            )
            report["original"] = {"id": original["id"], "policy": "archive"}
        else:
            report["original"] = {"policy": "delete_after_conversion"}

        migration_tier = tier(manifest, dependencies_resolved)
        if migration_tier == "manual_migration_required":
            report["status"] = migration_tier
            report["migrationTier"] = migration_tier
            report["verification"] = "not_converted"
        else:
            formats = await google.request(
                "GET", DRIVE + "/about", params={"fields": "importFormats"}
            )
            if SHEETS_MIME not in formats.get("importFormats", {}).get(XLSX.mime, []):
                raise ToolkitError(
                    "conversion_unavailable",
                    "Google does not currently offer Excel conversion for this account.",
                    422,
                )
            uploaded = await google.upload(
                root / "result/converted.xlsx",
                output_name,
                XLSX.mime,
                folder,
                convert=True,
                target=SHEETS_MIME,
            )
            report["outputs"].append({"kind": "spreadsheet", "id": uploaded["id"]})
            report["spreadsheetId"] = uploaded["id"]
            report["url"] = "https://docs.google.com/spreadsheets/d/" + uploaded["id"] + "/edit"
            spreadsheet = await google.request(
                "GET",
                SHEETS + uploaded["id"],
                params={"fields": "sheets.properties(sheetId,title,sheetType,hidden)"},
            )
            report["warnings"].extend(verify(manifest, spreadsheet))
            report["verification"] = "sheet_count_names_and_visibility_checked"
            report["status"] = "converted_with_review" if report["warnings"] else "converted"
            report["migrationTier"] = report["status"]
    except ToolkitError as exc:
        report["status"] = "failed_with_partial_outputs" if report.get("folderUrl") else "failed"
        report["warnings"].append(warning(exc.code, exc.message, classification=C.UNSUPPORTED))
        report["verification"] = "incomplete"

    if report.get("folderUrl"):
        report_path = root / "conversion-report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        try:
            saved = await google.upload(
                report_path,
                "Conversion report.json",
                "application/json",
                report["folderUrl"].rsplit("/", 1)[-1],
            )
            report["reportUrl"] = "https://drive.google.com/file/d/" + saved["id"] + "/view"
        except ToolkitError:
            report["warnings"].append(
                warning(
                    "report_upload_failed",
                    "The report could not be saved to Drive. Download it from this page.",
                )
            )
    return report
