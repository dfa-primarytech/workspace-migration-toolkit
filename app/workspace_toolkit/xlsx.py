"""Bounded Excel workbook preflight without cell values, formulas or VBA source.

The manifest contains structural facts needed by the batch planner and Google
boundary. Cell values, formula expressions and VBA source are deliberately not
serialised. Sheet names and external workbook filenames remain in the manifest
for structural verification and dependency matching. Web jobs delete it with
their workspace; the offline CLI retains it in the requested output directory.
Only the redacted report is suitable for sharing as content-free diagnostics.
"""

from __future__ import annotations

import json
import posixpath
import re
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .config import Settings
from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning
from .package import XLSM, XLSX, Format, Package, digest

NS = {
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xm": "http://schemas.microsoft.com/office/excel/2006/main",
}
REL_WORKSHEET = NS["r"] + "/worksheet"
MACRO_REL = "http://schemas.microsoft.com/office/2006/relationships/"
# International macro sheets use the same root element as ordinary macro sheets.
SHEET_TYPES = {
    REL_WORKSHEET: ("worksheet", "x", "worksheet"),
    NS["r"] + "/chartsheet": ("chartsheet", "x", "chartsheet"),
    NS["r"] + "/dialogsheet": ("dialogsheet", "x", "dialogsheet"),
    MACRO_REL + "xlMacrosheet": ("macrosheet", "xm", "macrosheet"),
    MACRO_REL + "xlIntlMacrosheet": ("intlMacrosheet", "xm", "macrosheet"),
}
REL_EXTERNAL = NS["r"] + "/externalLinkPath"
CELL = re.compile(r"^([A-Z]{1,4})([1-9][0-9]*)$")
RANGE = re.compile(r"^([A-Z]{1,4}[1-9][0-9]*)(?::([A-Z]{1,4}[1-9][0-9]*))?$")
GOOGLE_MAX_CELLS = 10_000_000
GOOGLE_MAX_COLUMNS = 18_278
GOOGLE_MAX_CELL_CHARS = 50_000


def q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def column_number(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + ord(char) - 64
    return value


def cell_position(reference: str) -> tuple[int, int] | None:
    match = CELL.fullmatch(reference.upper())
    if not match:
        return None
    return int(match.group(2)), column_number(match.group(1))


def range_size(reference: str | None) -> tuple[int, int]:
    if not reference:
        return 0, 0
    match = RANGE.fullmatch(reference.upper())
    if not match:
        return 0, 0
    positions = [cell_position(part) for part in match.groups() if part]
    valid = [position for position in positions if position]
    if not valid:
        return 0, 0
    return max(p[0] for p in valid), max(p[1] for p in valid)


def _text_length(element) -> int:
    return sum(len(node.text or "") for node in element.iter(q("x", "t")))


def _shared_string_lengths(package: Package) -> list[int]:
    name = "xl/sharedStrings.xml"
    if name not in package.names:
        return []
    return [_text_length(item) for item in package.xml(name).findall(q("x", "si"))]


# A date typed so Excel keeps it as text: 31/07/2023, 1.9.25, 07-31-2023.
DATE_TEXT = re.compile(r"\s*\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{2}|\d{4})\s*")


def _shared_string_dates(package: Package) -> set[int]:
    """Indexes of shared strings that are dates written as text. Only the
    indexes are kept: the text itself never reaches the manifest."""
    name = "xl/sharedStrings.xml"
    if name not in package.names:
        return set()
    items = package.xml(name).findall(q("x", "si"))
    return {
        i
        for i, item in enumerate(items)
        if DATE_TEXT.fullmatch("".join(node.text or "" for node in item.iter(q("x", "t"))))
    }


def _external_target(package: Package, link_part: str) -> str | None:
    for rel in package.relationships(link_part):
        if rel["type"] != REL_EXTERNAL or not rel["external"]:
            continue
        parsed = urlsplit(unquote(rel["target"]))
        candidate = posixpath.basename(parsed.path.replace("\\", "/"))
        return candidate or None
    return None


def _feature_inventory(package: Package) -> dict[str, int]:
    prefixes = {
        "charts": "xl/charts/",
        "pivotTables": "xl/pivotTables/",
        "queryTables": "xl/queryTables/",
        "externalLinks": "xl/externalLinks/externalLink",
        "forms": "xl/ctrlProps/",
        "activeX": "xl/activeX/",
        "embeddedObjects": "xl/embeddings/",
        "comments": "xl/comments",
        "threadedComments": "xl/threadedComments/",
    }
    result = {
        label: sum(
            1 for name in package.names if name.startswith(prefix) and not name.endswith(".rels")
        )
        for label, prefix in prefixes.items()
    }
    result["connections"] = int("xl/connections.xml" in package.names)
    result["customXml"] = sum(
        1 for name in package.names if name.startswith("customXml/") and name.endswith(".xml")
    )
    return result


def parse(package: Package, filename: str, source_sha: str) -> dict:
    workbook = package.xml(package.format.main_part)
    if workbook.tag != q("x", "workbook"):
        raise ToolkitError(
            "unsupported_namespace", "This Excel workbook format is not supported yet."
        )
    relationships = {rel["id"]: rel for rel in package.relationships(package.format.main_part)}
    shared_lengths = _shared_string_lengths(package)
    shared_dates = _shared_string_dates(package)
    features = _feature_inventory(package)
    external_targets = [
        target
        for name in sorted(package.names)
        if name.startswith("xl/externalLinks/externalLink") and name.endswith(".xml")
        if (target := _external_target(package, name))
    ]

    sheets: list[dict] = []
    total_grid_cells = 0
    declared_grid_cells = 0
    oversized_cells = 0
    formula_types: Counter[str] = Counter()
    error_cells = 0
    workbook_sheets = workbook.find(q("x", "sheets"))
    for index, sheet in enumerate(list(workbook_sheets) if workbook_sheets is not None else []):
        relationship = relationships.get(sheet.get(q("r", "id"), ""))
        if (
            not relationship
            or relationship["type"] not in SHEET_TYPES
            or relationship["external"]
            or relationship["missing"]
        ):
            raise ToolkitError("invalid_workbook", "A sheet reference is missing or invalid.")
        part = relationship["resolved"]
        root = package.xml(part)
        sheet_type, namespace, root_name = SHEET_TYPES[relationship["type"]]
        if root.tag != q(namespace, root_name):
            raise ToolkitError("invalid_workbook", "A sheet has invalid markup.")
        identity = {
            "index": index,
            "name": sheet.get("name", ""),
            "state": sheet.get("state", "visible"),
            "sourcePart": part,
            "sheetType": sheet_type,
            "protected": root.find(q("x", "sheetProtection")) is not None,
        }
        if sheet_type != "worksheet":
            # Preserve the part in the byte-for-byte copy, but do not invent
            # worksheet cell counts for charts, dialogs or executable macro sheets.
            sheets.append(identity)
            continue
        dimension = root.find(q("x", "dimension"))
        declared_rows, declared_columns = range_size(
            dimension.get("ref") if dimension is not None else None
        )
        actual_rows = actual_columns = populated = formulas = errors = text_dates = 0
        for cell in root.iter(q("x", "c")):
            position = cell_position(cell.get("r", ""))
            if position:
                actual_rows = max(actual_rows, position[0])
                actual_columns = max(actual_columns, position[1])
            formula = cell.find(q("x", "f"))
            value = cell.find(q("x", "v"))
            inline = cell.find(q("x", "is"))
            if formula is not None:
                formulas += 1
                formula_types[formula.get("t", "ordinary")] += 1
            if value is not None or inline is not None or formula is not None:
                populated += 1
            if cell.get("t") == "e":
                errors += 1
            length = _text_length(inline) if inline is not None else 0
            if cell.get("t") == "s" and value is not None:
                try:
                    shared_index = int(value.text or "")
                    length = shared_lengths[shared_index] if shared_index >= 0 else 0
                except (ValueError, IndexError):
                    raise ToolkitError(
                        "invalid_workbook", "A shared string reference is invalid."
                    ) from None
                if formula is None and shared_index in shared_dates:
                    text_dates += 1
            elif cell.get("t") == "inlineStr" and inline is not None and formula is None:
                if DATE_TEXT.fullmatch("".join(n.text or "" for n in inline.iter(q("x", "t")))):
                    text_dates += 1
            elif cell.get("t") == "str" and value is not None:
                length = len(value.text or "")
            if formula is not None:
                length = max(length, len(formula.text or ""))
            if length > GOOGLE_MAX_CELL_CHARS:
                oversized_cells += 1
        rows, columns = actual_rows, actual_columns
        total_grid_cells += rows * columns
        declared_grid_cells += declared_rows * declared_columns
        error_cells += errors
        sheets.append(
            {
                **identity,
                "rows": rows,
                "columns": columns,
                "declaredRows": declared_rows,
                "declaredColumns": declared_columns,
                "populatedCells": populated,
                "formulaCells": formulas,
                "errorCells": errors,
                "textDates": text_dates,
                "mergedRanges": sum(1 for _ in root.iter(q("x", "mergeCell"))),
                "conditionalFormats": sum(1 for _ in root.iter(q("x", "conditionalFormatting"))),
                "dataValidations": sum(1 for _ in root.iter(q("x", "dataValidation"))),
                "hyperlinks": sum(1 for _ in root.iter(q("x", "hyperlink"))),
            }
        )

    defined_names = workbook.find(q("x", "definedNames"))
    inventory = {
        "sheetCount": len(sheets),
        "totalGridCells": total_grid_cells,
        "declaredGridCells": declared_grid_cells,
        "populatedCells": sum(s.get("populatedCells", 0) for s in sheets),
        "formulaCells": sum(s.get("formulaCells", 0) for s in sheets),
        "textDates": sum(s.get("textDates", 0) for s in sheets),
        "chartSheets": sum(s["sheetType"] == "chartsheet" for s in sheets),
        "dialogSheets": sum(s["sheetType"] == "dialogsheet" for s in sheets),
        "macroSheets": sum(s["sheetType"] in {"macrosheet", "intlMacrosheet"} for s in sheets),
        "formulaTypes": dict(sorted(formula_types.items())),
        "errorCells": error_cells,
        "oversizedCells": oversized_cells,
        "definedNames": len(list(defined_names) if defined_names is not None else []),
        "veryHiddenSheets": sum(s["state"] == "veryHidden" for s in sheets),
        "protectedSheets": sum(s["protected"] for s in sheets),
        **features,
    }
    macro_parts = sorted(name for name in package.names if "vbaproject" in name.lower())
    macros = [
        {"sha256": digest(data := package.read(name)), "byteLength": len(data)}
        for name in macro_parts
    ]
    workbook_protection = workbook.find(q("x", "workbookProtection")) is not None
    inventory["workbookProtected"] = int(workbook_protection)
    inventory["vbaProjects"] = len(macros)
    warnings = findings(inventory, sheets, len(external_targets))
    return {
        "schemaVersion": "1.0",
        "source": {
            "type": package.format.key,
            "filename": filename,
            "sha256": source_sha,
            "byteLength": 0,
        },
        "document": {"sheetCount": len(sheets)},
        "sheets": sheets,
        "assets": {},
        "inventory": inventory,
        "externalWorkbookTargets": external_targets,
        "macros": macros,
        "warnings": warnings,
    }


def findings(inventory: dict, sheets: list[dict], external_count: int) -> list[dict]:
    result: list[dict] = []
    for sheet in sheets:
        sheet_type = sheet["sheetType"]
        if sheet_type == "worksheet":
            continue
        if sheet_type == "chartsheet":
            code = "chart_sheet_needs_review"
            message = (
                "A chart sheet is preserved in the workbook sent to Google. "
                "Its chart layout and editability are not verified; review it after import."
            )
        elif sheet_type == "dialogsheet":
            code = "dialog_sheet_needs_manual_migration"
            message = "A dialog sheet was detected. Its controls need manual migration."
        else:
            code = "macro_sheet_needs_manual_migration"
            message = (
                "An Excel macro sheet was detected. Its automation needs manual migration "
                "and is never executed or translated automatically."
            )
        result.append(
            warning(
                code,
                message,
                sheetIndex=sheet["index"],
                sheetType=sheet_type,
                classification=C.UNSUPPORTED,
            )
        )
    if inventory["totalGridCells"] > GOOGLE_MAX_CELLS:
        result.append(
            warning(
                "google_cell_limit",
                "This workbook exceeds the Google Sheets cell limit and needs to be split before migration.",
                cellCount=inventory["totalGridCells"],
                limit=GOOGLE_MAX_CELLS,
                classification=C.UNSUPPORTED,
            )
        )
    elif inventory["declaredGridCells"] > GOOGLE_MAX_CELLS:
        result.append(
            warning(
                "declared_extent_needs_review",
                "The workbook declares a grid larger than Google Sheets accepts, but its actual cell extent is within the limit. Review the workbook after import.",
                declaredCellCount=inventory["declaredGridCells"],
                observedCellCount=inventory["totalGridCells"],
                limit=GOOGLE_MAX_CELLS,
                classification=C.UNSUPPORTED,
            )
        )
    if any(sheet.get("columns", 0) > GOOGLE_MAX_COLUMNS for sheet in sheets):
        result.append(
            warning(
                "google_column_limit",
                "A worksheet exceeds the Google Sheets column limit and needs manual migration.",
                limit=GOOGLE_MAX_COLUMNS,
                classification=C.UNSUPPORTED,
            )
        )
    if inventory["oversizedCells"]:
        result.append(
            warning(
                "cell_text_limit",
                "Some cells contain more text than Google Sheets accepts.",
                cellCount=inventory["oversizedCells"],
                limit=GOOGLE_MAX_CELL_CHARS,
                classification=C.UNSUPPORTED,
            )
        )
    if inventory["formulaCells"]:
        result.append(
            warning(
                "formulas_need_review",
                "Formula results may change after import and need review.",
                formulaCount=inventory["formulaCells"],
                errorCellCount=inventory["errorCells"],
                classification=C.SUBSTITUTED,
            )
        )
    if inventory.get("textDates"):
        count = inventory["textDates"]
        result.append(
            warning(
                "dates_stored_as_text",
                f"{count} date{'s are' if count > 1 else ' is'} typed as text, not as "
                f"{'dates' if count > 1 else 'a date'}. The Sheet is set to read dates the UK "
                "way, so formulas can use them, but they won't sort or filter as dates. "
                "Retype them to be sure.",
                cellCount=count,
                sheets=[s["index"] for s in sheets if s.get("textDates")],
                classification=C.SUBSTITUTED,
            )
        )
    if external_count:
        result.append(
            warning(
                "external_workbook_links",
                "This workbook links to other workbooks. A batch plan must resolve those files before migration.",
                linkCount=external_count,
                classification=C.UNSUPPORTED,
            )
        )
    for key, code, message, classification in (
        (
            "pivotTables",
            "pivot_tables_need_review",
            "Pivot tables were detected and need review after import.",
            C.SUBSTITUTED,
        ),
        (
            "queryTables",
            "queries_need_manual_migration",
            "Workbook queries cannot be migrated automatically.",
            C.UNSUPPORTED,
        ),
        (
            "connections",
            "connections_need_manual_migration",
            "External data connections cannot be migrated automatically.",
            C.UNSUPPORTED,
        ),
        (
            "forms",
            "forms_need_manual_migration",
            "Form controls cannot be migrated automatically.",
            C.UNSUPPORTED,
        ),
        (
            "activeX",
            "activex_need_manual_migration",
            "ActiveX controls cannot be migrated automatically.",
            C.UNSUPPORTED,
        ),
        (
            "embeddedObjects",
            "embedded_objects_need_manual_migration",
            "Embedded objects cannot be migrated automatically.",
            C.UNSUPPORTED,
        ),
        (
            "vbaProjects",
            "vba_needs_manual_migration",
            "VBA was inventoried but is never executed or translated automatically.",
            C.UNSUPPORTED,
        ),
    ):
        if inventory[key]:
            result.append(
                warning(code, message, count=inventory[key], classification=classification)
            )
    if inventory["charts"]:
        result.append(
            warning(
                "charts_need_review",
                "Charts were detected and need visual review after import.",
                count=inventory["charts"],
                classification=C.SUBSTITUTED,
            )
        )
    if inventory["veryHiddenSheets"]:
        result.append(
            warning(
                "very_hidden_sheets",
                "Very hidden worksheets need review after import.",
                count=inventory["veryHiddenSheets"],
                classification=C.SUBSTITUTED,
            )
        )
    if inventory["protectedSheets"] or inventory["workbookProtected"]:
        result.append(
            warning(
                "protection_needs_review",
                "Workbook or worksheet protection may change during import.",
                classification=C.SUBSTITUTED,
            )
        )
    return result


def tier(manifest: dict, dependencies_resolved: bool = False) -> str:
    hard_codes = {
        "google_cell_limit",
        "google_column_limit",
        "cell_text_limit",
        "queries_need_manual_migration",
        "connections_need_manual_migration",
        "forms_need_manual_migration",
        "activex_need_manual_migration",
        "embedded_objects_need_manual_migration",
        "vba_needs_manual_migration",
        "dialog_sheet_needs_manual_migration",
        "macro_sheet_needs_manual_migration",
    }
    codes = {item["code"] for item in manifest["warnings"]}
    if codes & hard_codes or (manifest["externalWorkbookTargets"] and not dependencies_resolved):
        return "manual_migration_required"
    return "converted_with_review" if manifest["warnings"] else "converted"


def analysis_report(manifest: dict) -> dict:
    inventory = manifest["inventory"]
    return {
        "schemaVersion": "1.0",
        "status": "analysed",
        "migrationTier": tier(manifest),
        "sourceSha256": manifest["source"]["sha256"],
        "pages": manifest["document"]["sheetCount"],
        "sheetCount": manifest["document"]["sheetCount"],
        "cellCounts": {
            key: inventory[key]
            for key in (
                "totalGridCells",
                "declaredGridCells",
                "populatedCells",
                "formulaCells",
                "errorCells",
                "oversizedCells",
                "textDates",
            )
        },
        "featureCounts": {
            key: inventory[key]
            for key in (
                "charts",
                "chartSheets",
                "dialogSheets",
                "macroSheets",
                "pivotTables",
                "queryTables",
                "connections",
                "forms",
                "activeX",
                "embeddedObjects",
                "externalLinks",
                "vbaProjects",
            )
        },
        "assetCounts": {},
        "fonts": [],
        "warnings": manifest["warnings"],
        "verification": "not_converted",
        "classificationBasis": "Structural preflight only; Google compatibility has not been verified live.",
    }


def analyse(path: Path, output: Path, settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    fmt: Format = XLSM if path.suffix.lower() == ".xlsm" else XLSX
    package = Package(path, settings, fmt)
    try:
        output.mkdir(parents=True, exist_ok=True)
        manifest = parse(package, path.name, digest(path.read_bytes()))
        manifest["source"]["byteLength"] = path.stat().st_size
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (output / "report.json").write_text(
            json.dumps(analysis_report(manifest), indent=2), encoding="utf-8"
        )
        # The credential-free worker emits the exact package the native importer
        # will receive. No macros are stripped or executed; macro workbooks are
        # blocked by the conversion tier before upload as a Google Sheet.
        shutil.copyfile(path, output / ("converted" + fmt.suffix))
        return manifest
    finally:
        package.close()
