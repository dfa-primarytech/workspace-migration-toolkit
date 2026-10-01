"""A macro-enabled workbook, made ready for Google Sheets (DECISIONS.md, 2026-10-01).

Google won't convert an .xlsm at all (live test, 2026-10-01: Drive lists no
import for its type), so the worker writes the workbook again as a plain
.xlsx: the macro project and everything that declares it are taken out, and
the workbook part is declared as an ordinary workbook. Every edit is checked,
and the result is opened again as an .xlsx before it is used.

The macros themselves are not lost. Their source is saved as text, and the
recorded ones are written as Apps Script (apps_script.py); both go into the
person's own conversion folder. The manifest and the report only ever get
counts. Nothing is run.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .apps_script import translate
from .config import Settings
from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning
from .package import (
    CONTENT_NS,
    XLSM_MAIN_MIME,
    XLSX,
    XLSX_MAIN_MIME,
    Package,
    _parsed,
    tags,
    without_overrides,
    without_relationships,
)
from .vba import VbaUnreadable, read_modules

DEFAULTS = tags(b"Default")
VBA_TYPES = ("vbaproject", "macroenabled", "vbadata")
ORIGINAL_NAME = "original-vba.txt"
SCRIPT_NAME = "apps-script.txt"
# What each file is called in the person's folder.
UPLOADED = {
    ORIGINAL_NAME: "Macros – original Excel VBA.txt",
    SCRIPT_NAME: "Macros for Google Sheets (Apps Script).txt",
}


def _is_macro_part(name: str) -> bool:
    lowered = name.lower()
    return "vbaproject" in lowered or lowered.endswith("vbadata.xml")


def macro_free(package: Package, destination: Path, settings: Settings) -> None:
    """Writes `package` to `destination` as an .xlsx with no macro project."""
    names = [i.filename for i in package.zip.infolist() if i.filename in package.names]
    dropped = {n for n in names if _is_macro_part(n)}
    parts: dict[str, bytes] = {}
    for name in names:
        if name in dropped:
            continue
        parts[name] = package.read(name)

    rels_name = "xl/_rels/workbook.xml.rels"
    if rels_name in parts:
        ids = {
            rel["id"]
            for rel in package.relationships(package.format.main_part)
            if rel["type"].lower().endswith("/vbaproject")
        }
        if ids:
            edited = without_relationships(parts[rels_name], ids)
            if edited is None:
                raise ToolkitError(
                    "macros_not_removable", "The workbook's macros couldn't be taken out."
                )
            parts[rels_name] = edited

    types = without_overrides(parts["[Content_Types].xml"], dropped)
    if types is not None:
        types = DEFAULTS.sub(
            lambda m: (
                b"" if any(t.encode() in m.group(0).lower() for t in VBA_TYPES) else m.group(0)
            ),
            types,
        )
        types = types.replace(XLSM_MAIN_MIME.encode(), XLSX_MAIN_MIME.encode())
    root = _parsed(types) if types is not None else None
    if (
        types is None
        or root is None
        or any(
            t in (node.get("ContentType") or "").lower()
            for node in root.iter()
            if node.tag in {f"{{{CONTENT_NS}}}Default", f"{{{CONTENT_NS}}}Override"}
            for t in VBA_TYPES
        )
    ):
        raise ToolkitError("macros_not_removable", "The workbook's macros couldn't be taken out.")
    parts["[Content_Types].xml"] = types

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    # Proven, not assumed: it must open as a plain workbook, macros and all gone.
    Package(destination, settings, XLSX).close()


def _original_text(modules) -> str:
    sections = []
    for module in modules:
        code = "\n".join(
            line for line in module.source.split("\n") if not line.startswith("Attribute VB_")
        ).strip()
        if code:
            sections.append(f"' ===== {module.name} =====\n{code}\n")
    return "\n".join(sections)


def prepare(package: Package, output: Path) -> tuple[dict, list[dict]]:
    """Saves the macros as text and as Apps Script under `output/macros`.

    Returns a content-free summary for the manifest, and the notes for the
    report. A project this reader can't follow is reported, and the workbook
    still converts: the original, macros and all, is kept in the folder.
    """
    project = next((n for n in sorted(package.names) if n.lower().endswith("vbaproject.bin")), None)
    if project is None:
        return {"read": False, "files": []}, []
    try:
        modules = read_modules(package.read(project))
    except VbaUnreadable:
        return {"read": False, "files": []}, [
            warning(
                "macros_unreadable",
                "The workbook's macros couldn't be read, so they weren't copied across. "
                "The original workbook in the folder still has them.",
                classification=C.UNSUPPORTED,
            )
        ]
    folder = output / "macros"
    folder.mkdir(exist_ok=True)
    files = []
    original = _original_text(modules)
    if original:
        (folder / ORIGINAL_NAME).write_text(original, encoding="utf-8")
        files.append(ORIGINAL_NAME)
    translation = translate(modules)
    counts = translation.summary()
    if translation.macros:
        (folder / SCRIPT_NAME).write_text(translation.script, encoding="utf-8")
        files.append(SCRIPT_NAME)
    summary = {"read": True, "modules": len(modules), **counts, "files": files}
    return summary, notes(counts, bool(original))


def notes(counts: dict, has_code: bool) -> list[dict]:
    total, full = counts["macros"], counts["fullyTranslated"]
    script, original = UPLOADED[SCRIPT_NAME], UPLOADED[ORIGINAL_NAME]
    how = (
        f"To use {'them' if total > 1 else 'it'}: open the Google Sheet, choose Extensions → "
        f'Apps Script, paste in "{script}" from the folder, and save. Reload the Sheet and '
        "use the Macros menu."
    )
    if total and full == total:
        return [
            warning(
                "macros_translated",
                f"The workbook's {_count(total)} {'were' if total > 1 else 'was'} written as "
                f"Google Apps Script. {how}",
                macroCount=total,
                classification=C.SUBSTITUTED,
            )
        ]
    if total:
        lines = counts["untranslatedLines"]
        done = (
            "The workbook's macro was written as Google Apps Script, but"
            if total == 1
            else f"{full} of the workbook's {total} macros were written in full as Google "
            "Apps Script, and in the others"
        )
        return [
            warning(
                "macros_partly_translated",
                f"{done} {lines} line{'s' if lines != 1 else ''} couldn't be: "
                f'{"they are" if lines != 1 else "it is"} marked "Not translated" in "{script}". '
                f'{how} The original code is in "{original}".',
                macroCount=total,
                fullyTranslated=full,
                untranslatedLines=counts["untranslatedLines"],
                classification=C.UNSUPPORTED,
            )
        ]
    if has_code:
        return [
            warning(
                "macros_not_translated",
                "The workbook's code isn't recorded macros, so it couldn't be written as Apps "
                f'Script and needs rewriting by hand. It is saved in the folder as "{original}".',
                classification=C.UNSUPPORTED,
            )
        ]
    return []


def _count(n: int) -> str:
    return "macro" if n == 1 else f"{n} macros"
