"""Bounded, content-free Excel workbook preflight.

The manifest contains structural facts needed by the batch planner and Google
boundary. Cell values, formula expressions and VBA source are deliberately not
serialised. The job workspace is temporary and is the only place the manifest
exists before its redacted report is returned.
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
}
REL_WORKSHEET = NS["r"] + "/worksheet"
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
    features = _feature_inventory(package)
    external_targets = [
        target
        for name in sorted(package.names)
        if name.startswith("xl/externalLinks/externalLink") and name.endswith(".xml")
        if (target := _external_target(package, name))
    ]

    sheets: list[dict] = []
    total_grid_cells = 0
    oversized_cells = 0
    formula_types: Counter[str] = Counter()
    error_cells = 0
    workbook_sheets = workbook.find(q("x", "sheets"))
    for index, sheet in enumerate(
        list(workbook_sheets) if workbook_sheets is not None else [], start=1
    ):
        relationship = relationships.get(sheet.get(q("r", "id"), ""))
        if not relationship or relationship["type"] != REL_WORKSHEET or relationship["external"]:
            raise ToolkitError("invalid_workbook", "A worksheet reference is missing or invalid.")
        part = relationship["resolved"]
        root = package.xml(part)
        if root.tag != q("x", "worksheet"):
            raise ToolkitError("invalid_workbook", "A worksheet has invalid markup.")
        dimension = root.find(q("x", "dimension"))
        rows, columns = range_size(dimension.get("ref") if dimension is not None else None)
        actual_rows = actual_columns = populated = formulas = errors = 0
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
            elif cell.get("t") == "str" and value is not None:
                length = len(value.text or "")
            if formula is not None:
                length = max(length, len(formula.text or ""))
            if length > GOOGLE_MAX_CELL_CHARS:
                oversized_cells += 1
        rows, columns = max(rows, actual_rows), max(columns, actual_columns)
        total_grid_cells += rows * columns
        error_cells += errors
        sheets.append(
            {
                "index": index,
                "name": sheet.get("name", ""),
                "state": sheet.get("state", "visible"),
                "sourcePart": part,
                "rows": rows,
                "columns": columns,
                "populatedCells": populated,
                "formulaCells": formulas,
                "errorCells": errors,
                "mergedRanges": sum(1 for _ in root.iter(q("x", "mergeCell"))),
                "conditionalFormats": sum(1 for _ in root.iter(q("x", "conditionalFormatting"))),
                "dataValidations": sum(1 for _ in root.iter(q("x", "dataValidation"))),
                "hyperlinks": sum(1 for _ in root.iter(q("x", "hyperlink"))),
                "protected": root.find(q("x", "sheetProtection")) is not None,
            }
        )

    defined_names = workbook.find(q("x", "definedNames"))
    inventory = {
        "sheetCount": len(sheets),
        "totalGridCells": total_grid_cells,
        "populatedCells": sum(s["populatedCells"] for s in sheets),
        "formulaCells": sum(s["formulaCells"] for s in sheets),
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
    if any(sheet["columns"] > GOOGLE_MAX_COLUMNS for sheet in sheets):
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
                "populatedCells",
                "formulaCells",
                "errorCells",
                "oversizedCells",
            )
        },
        "featureCounts": {
            key: inventory[key]
            for key in (
                "charts",
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
