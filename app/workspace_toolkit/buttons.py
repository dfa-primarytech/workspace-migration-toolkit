"""A workbook's macro buttons, and which macro each one runs in Google.

Google brings an Excel shape across as a drawing, but never what it ran: a
drawing's script is set only by Apps Script (Drawing.setOnAction), not by the
Sheets API. So each button is found here, by sheet and anchor cell, and its
macro is named; the script added to the Sheet links them (apps_script.py).

A button is linked to the macro Excel assigned it. A workbook that has been
through Google already has lost that assignment (live test, 2026-10-01), so
a button with none is linked only under one strict rule (DECISIONS.md,
2026-10-01): the workbook has exactly one macro, and the button's label
begins with that macro's name in whole words ("Repair Columns" runs Repair;
"Repairs" doesn't). Anything else is left unlinked, and the report says so.

Excel's form-control buttons (Insert > Form Controls) are not drawings, and
Google drops them on import; they are only counted, for the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ToolkitError
from .package import Package

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
DRAWING_REL = R + "/drawing"
VML_REL = R + "/vmlDrawing"
ANCHORS = (f"{{{XDR}}}twoCellAnchor", f"{{{XDR}}}oneCellAnchor")
SHAPES = (f"{{{XDR}}}sp", f"{{{XDR}}}pic")
FORM_BUTTON = re.compile(rb"ObjectType\s*=\s*[\"']Button[\"']", re.I)
MOST = 500  # buttons read per workbook; past this, the rest are not linked


@dataclass(frozen=True)
class Button:
    sheet: str
    row: int  # 1-based, as Apps Script's getAnchorRow()
    column: int
    label: str
    macro: str  # the macro Excel assigned it, as written; "" if none


@dataclass(frozen=True)
class Link:
    sheet: str
    row: int
    column: int
    function: str  # the Apps Script function the button runs
    by: str  # "assigned" or "label"


@dataclass
class Found:
    buttons: list[Button]
    form_buttons: int = 0  # Excel form controls, which Google drops


def _rels(package: Package, part: str) -> dict[str, dict]:
    return {rel["id"]: rel for rel in package.relationships(part)}


def read_buttons(package: Package) -> Found:
    """Every shape on a worksheet that has a label or an assigned macro."""
    found = Found([])
    try:
        workbook = package.xml(package.format.main_part)
        sheets = workbook.find(f"{{{X}}}sheets")
        links = _rels(package, package.format.main_part)
        for sheet in list(sheets) if sheets is not None else []:
            rel = links.get(sheet.get(f"{{{R}}}id", ""))
            if not rel or rel["external"] or rel["missing"]:
                continue
            for drawing in package.relationships(rel["resolved"]):
                if drawing["external"] or drawing["missing"]:
                    continue
                if drawing["type"] == VML_REL:
                    found.form_buttons += len(
                        FORM_BUTTON.findall(package.read(drawing["resolved"]))
                    )
                elif drawing["type"] == DRAWING_REL:
                    found.buttons += _shapes(package, drawing["resolved"], sheet.get("name", ""))
                if len(found.buttons) >= MOST:
                    found.buttons = found.buttons[:MOST]
                    return found
    except ToolkitError:
        # A drawing this reader can't follow only means no buttons are linked:
        # the workbook itself was already read and checked by xlsx.analyse.
        return Found([])
    return found


def _shapes(package: Package, part: str, sheet: str) -> list[Button]:
    buttons = []
    for anchor in package.xml(part):
        if anchor.tag not in ANCHORS or (start := anchor.find(f"{{{XDR}}}from")) is None:
            continue
        try:
            row = int(start.findtext(f"{{{XDR}}}row", "")) + 1
            column = int(start.findtext(f"{{{XDR}}}col", "")) + 1
        except ValueError:
            continue
        for shape in anchor:
            if shape.tag not in SHAPES:
                continue
            label = " ".join(
                "".join(t.text or "" for t in p.iter(f"{{{A}}}t")) for p in shape.iter(f"{{{A}}}p")
            ).strip()
            macro = (shape.get("macro") or "").strip()
            if label or macro:
                buttons.append(Button(sheet, row, column, label, macro))
    return buttons


def _vba_name(assigned: str) -> str:
    """ "[0]!Module1.Repair" or "'Book.xlsm'!Repair" is the macro Repair."""
    return assigned.rsplit("!", 1)[-1].rsplit(".", 1)[-1].strip("'").casefold()


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def _label_names(label: str, name: str) -> bool:
    """The label begins with the macro's name, in whole words: "Repair
    Columns" names Repair and RepairColumns, never Repairs or Rep."""
    words, wanted = _words(label), "".join(_words(name))
    return bool(wanted) and any("".join(words[:k]) == wanted for k in range(1, len(words) + 1))


def link(buttons: list[Button], macros: list[tuple[str, str]]) -> tuple[list[Link], int]:
    """The links, from (Excel name, function) pairs, and how many buttons
    Excel assigned a macro that isn't among them. A shape with only a label
    that names no macro is not counted: it may be just a text box."""
    by_name = {name.casefold(): function for name, function in macros}
    only = macros[0] if len(macros) == 1 else None
    links: list[Link] = []
    missed = 0
    for b in buttons:
        if b.macro:
            if function := by_name.get(_vba_name(b.macro)):
                links.append(Link(b.sheet, b.row, b.column, function, "assigned"))
            else:
                missed += 1
        elif only and _label_names(b.label, only[0]):
            links.append(Link(b.sheet, b.row, b.column, only[1], "label"))
    return links, missed
