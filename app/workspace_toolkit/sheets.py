"""Google Sheets native-import boundary.

No formula or VBA translation occurs here. Drive performs the ordinary XLSX
import; the Sheet is then given the UK locale and the person's time zone.
Structural read-back uses the Sheets API through the existing narrow
``drive.file`` grant and never places cell contents in logs or reports.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ToolkitError
from .google import DRIVE, SEPARATOR, clean_name
from .macros import UPLOADED
from .model import Compatibility as C
from .model import warning
from .package import XLSM, XLSX
from .xlsx import analysis_report, tier

SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets/"
ORIGINAL_POLICIES = {"archive", "delete_after_conversion"}

# Every converted Sheet reads dates day first, as UK Excel does: a Sheet in a
# US locale reads "31/07/2023" as no date at all, and every formula built on
# it gives #VALUE! (a nursery calculator, live test 2026-10-01). The time
# zone is the person's own, from their browser, so TODAY() follows their day.
LOCALE = "en_GB"
DEFAULT_TIME_ZONE = "Europe/London"

# Why a workbook was not converted, in a teacher's words, by finding code.
NOT_CONVERTED_BECAUSE = {
    "google_cell_limit": "it has more cells than Google Sheets allows",
    "google_column_limit": "it has more columns than Google Sheets allows",
    "cell_text_limit": "some cells hold more text than Google Sheets allows",
    "queries_need_manual_migration": "it fetches data with queries",
    "connections_need_manual_migration": "it connects to outside data",
    "forms_need_manual_migration": "it has form controls",
    "activex_need_manual_migration": "it has ActiveX controls",
    "embedded_objects_need_manual_migration": "it has embedded objects",
    "macros_not_removable": "its macros couldn't be taken out safely",
    "dialog_sheet_needs_manual_migration": "it has a dialog sheet",
    "macro_sheet_needs_manual_migration": "it has an Excel 4 macro sheet",
    "external_workbook_links": "it links to other workbooks",
}


def not_converted_because(manifest: dict) -> str:
    reasons = [
        NOT_CONVERTED_BECAUSE[w["code"]]
        for w in manifest["warnings"]
        if w["code"] in NOT_CONVERTED_BECAUSE
    ]
    if not reasons:
        return "Not converted: it needs moving into Google Sheets by hand. The report in the folder says why."
    listed = reasons[0] if len(reasons) == 1 else ", ".join(reasons[:-1]) + " and " + reasons[-1]
    return f"Not converted: {listed}. The original is saved in the folder."


async def save_macros(folder_path: Path, google, folder: str, report: dict) -> None:
    """Puts the macros, as written by macros.prepare, in the person's folder.
    A copy that fails is noted; the Sheet itself has already converted."""
    for name, shown in UPLOADED.items():
        path = folder_path / name
        if not path.exists():
            continue
        try:
            saved = await google.upload(path, shown, "text/plain", folder)
        except ToolkitError:
            report["warnings"].append(
                warning(
                    "macros_not_saved",
                    f'"{shown}" couldn\'t be saved in the folder. The original workbook there '
                    "still has the macros.",
                    classification=C.UNSUPPORTED,
                )
            )
            continue
        report["assetOutputs"].append({"kind": "macros", "name": shown, "id": saved["id"]})


async def uk_settings(google, spreadsheet_id: str, time_zone: str | None) -> dict | None:
    """Sets the Sheet's locale to UK and its time zone to the person's own,
    or London if Google refuses theirs. None if neither could be set: the
    Sheet still converted, and the caller says so."""
    for zone in dict.fromkeys([time_zone or DEFAULT_TIME_ZONE, DEFAULT_TIME_ZONE]):
        try:
            await google.request(
                "POST",
                SHEETS + spreadsheet_id + ":batchUpdate",
                json={
                    "requests": [
                        {
                            "updateSpreadsheetProperties": {
                                "properties": {"locale": LOCALE, "timeZone": zone},
                                "fields": "locale,timeZone",
                            }
                        }
                    ]
                },
            )
            return {"locale": LOCALE, "timeZone": zone}
        except ToolkitError:
            continue
    return None


def verify(manifest: dict, spreadsheet: dict) -> list[dict]:
    findings: list[dict] = []
    converted = spreadsheet.get("sheets", [])
    source = manifest["sheets"]
    if len(converted) != len(source):
        findings.append(
            warning(
                "sheet_count_changed",
                "The number of sheets changed during import.",
                sourceCount=len(source),
                convertedCount=len(converted),
                classification=C.UNSUPPORTED,
            )
        )
    for original, target in zip(source, converted, strict=False):
        properties = target.get("properties", {})
        if (
            original.get("sheetType", "worksheet") == "worksheet"
            and properties.get("sheetType", "GRID") != "GRID"
        ):
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
    original_name: str = "",
    time_zone: str | None = None,
) -> dict:
    if original_policy not in ORIGINAL_POLICIES:
        raise ValueError("Unknown original workbook policy")
    document = clean_name(original_name)
    if document:
        output_name = f"{document}{SEPARATOR}converted"
    report = progress if progress is not None else {}
    report.update(analysis_report(manifest))
    report.update(status="converting", outputs=[], assetOutputs=[])
    fmt = XLSM if manifest["source"]["type"] == "xlsm" else XLSX
    try:
        folder = await google.folder(output_name)
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
            report["stoppedBecause"] = not_converted_because(manifest)
        else:
            formats = await google.request(
                "GET", DRIVE + "/about", params={"fields": "importFormats"}
            )
            # Always sent as .xlsx: the worker wrote a macro workbook again
            # without its macros (macros.py), as Google converts no .xlsm.
            if SHEETS_MIME not in formats.get("importFormats", {}).get(XLSX.mime, []):
                raise ToolkitError(
                    "conversion_unavailable",
                    "Google does not currently offer Excel conversion for this account.",
                    422,
                )
            uploaded = await google.upload(
                root / "result" / "converted.xlsx",
                output_name,
                XLSX.mime,
                folder,
                convert=True,
                target=SHEETS_MIME,
            )
            await save_macros(root / "result" / "macros", google, folder, report)
            report["outputs"].append({"kind": "spreadsheet", "id": uploaded["id"]})
            report["spreadsheetId"] = uploaded["id"]
            report["url"] = "https://docs.google.com/spreadsheets/d/" + uploaded["id"] + "/edit"
            settings = await uk_settings(google, uploaded["id"], time_zone)
            if settings:
                report["spreadsheetSettings"] = settings
            else:
                report["warnings"].append(
                    warning(
                        "locale_not_set",
                        "The Sheet's region couldn't be set to the UK, so dates may be read "
                        "month first. Set it under File → Settings → Locale.",
                        classification=C.UNSUPPORTED,
                    )
                )
            spreadsheet = await google.request(
                "GET",
                SHEETS + uploaded["id"],
                params={"fields": "sheets.properties(sheetId,title,sheetType,hidden)"},
            )
            report["warnings"].extend(verify(manifest, spreadsheet))
            report["verification"] = "sheet_count_names_and_visibility_checked"
            # Always with review: the read-back checks the sheets' structure,
            # names, types and visibility, not formulas, formatting, charts,
            # pivots, validation or protection, so verify() always asks for a
            # look. Plain "converted" is kept for stronger verification than
            # this (docs/xlsx-migration.md), not for a workbook with no notes.
            report["status"] = "converted_with_review"
            report["migrationTier"] = report["status"]
    except ToolkitError as exc:
        report["status"] = "failed_with_partial_outputs" if report.get("folderUrl") else "failed"
        report["warnings"].append(warning(exc.code, exc.message, classification=C.UNSUPPORTED))
        report["verification"] = "incomplete"

    # Saved to Drive by the caller, once, with everything added after this
    # returns (see google.save_report and web.py, #121).
    return report
