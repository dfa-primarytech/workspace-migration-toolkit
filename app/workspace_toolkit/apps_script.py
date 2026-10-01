"""Recorded Excel macros, written as Google Apps Script.

Bounded on purpose (DECISIONS.md, 2026-10-01): this is not a VBA translator.
It knows the statements Excel's macro recorder writes -- select a range, fill
it down, copy and paste, clear it, set a value or a formula, bold it, colour
it, switch sheet, insert or delete rows and columns, show a message -- each
mapped to its Apps Script equivalent, in order, keeping track of what is
selected as the recorder does. Scrolling and other window-only steps are
dropped: they change nothing in the workbook.

Any other line is kept as a comment and counted, never guessed at: a macro
with any such line is "partly translated", and the report says so. Nothing
here runs code; no language model is involved.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .vba import Module

# Window-only steps the recorder writes: nothing in the workbook changes.
NOISE = re.compile(
    r"^(ActiveWindow\.|Application\.(CutCopyMode|ScreenUpdating|DisplayAlerts|"
    r"Goto)\b|Selection\.End\(|Range\(\"[A-Z]+[0-9]+\"\)\.Activate$)",
    re.I,
)
ADDRESS = r"\"(\$?[A-Za-z]{1,3}\$?[0-9]+(?::\$?[A-Za-z]{1,3}\$?[0-9]+)?)\""
ROWS = r"\"(\$?[0-9]+(?::\$?[0-9]+)?)\""
COLUMNS = r"\"(\$?[A-Za-z]{1,3}(?::\$?[A-Za-z]{1,3})?)\""
STRING = r"\"((?:[^\"]|\"\")*)\""
SHEET = re.compile(r"^(?:Sheets|Worksheets)\(" + STRING + r"\)\.(?:Select|Activate)$", re.I)
SELECT = re.compile(r"^Range\(" + ADDRESS + r"\)\.(?:Select|Activate)$", re.I)
SELECT_ROWS = re.compile(r"^Rows\(" + ROWS + r"\)\.Select$", re.I)
SELECT_COLUMNS = re.compile(r"^Columns\(" + COLUMNS + r"\)\.Select$", re.I)
SELECT_CELL = re.compile(r"^Cells\(([0-9]+), *([0-9]+)\)\.Select$", re.I)
AUTOFILL = re.compile(
    r"^Selection\.AutoFill Destination:=Range\(" + ADDRESS + r"\)(?:, *Type:=xlFillDefault)?$",
    re.I,
)
TARGET = r"(Selection|ActiveCell|Range\(" + ADDRESS + r"\))"
SET_VALUE = re.compile(r"^" + TARGET + r"\.(Value|Value2)? *= *(.+)$", re.I)
SET_FORMULA = re.compile(r"^" + TARGET + r"\.(Formula|FormulaR1C1) *= *" + STRING + r"$", re.I)
CLEAR = re.compile(r"^" + TARGET + r"\.(ClearContents|Clear|ClearFormats)$", re.I)
COPY = re.compile(r"^" + TARGET + r"\.Copy$", re.I)
PASTE = re.compile(r"^ActiveSheet\.Paste$", re.I)
PASTE_SPECIAL = re.compile(
    r"^Selection\.PasteSpecial Paste:=(xlPasteValues|xlPasteFormats|xlPasteAll)\b.*$", re.I
)
INSERT = re.compile(
    r"^Selection\.(EntireRow\.|EntireColumn\.)?Insert(?: Shift:=(xlDown|xlToRight))?"
    r"(?:, *CopyOrigin:=\w+)?$",
    re.I,
)
DELETE = re.compile(
    r"^Selection\.(EntireRow\.|EntireColumn\.)?Delete(?: Shift:=(xlUp|xlToLeft))?$", re.I
)
FONT = re.compile(r"^Selection\.Font\.(Bold|Italic|Underline|Size|Name|Color) *= *(.+)$", re.I)
FILL = re.compile(r"^Selection\.Interior\.Color *= *(.+)$", re.I)
MSGBOX = re.compile(r"^MsgBox(?: *\(| +)" + STRING + r"\)?$", re.I)
SUB = re.compile(r"^(?:Public |Private )?Sub ([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*$", re.I)
END_SUB = re.compile(r"^End Sub$", re.I)
# A VBA name that JavaScript keeps for itself, or that the script itself uses,
# gets a prefix: function delete() would not load at all.
RESERVED = {
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "debugger",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "export",
    "extends",
    "false",
    "finally",
    "for",
    "function",
    "if",
    "import",
    "in",
    "instanceof",
    "let",
    "new",
    "null",
    "return",
    "static",
    "super",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "var",
    "void",
    "while",
    "with",
    "yield",
    "await",
    "implements",
    "interface",
    "package",
    "private",
    "protected",
    "public",
    "onopen",
    "onedit",
    "oninstall",
    "doget",
    "dopost",
    "spreadsheetapp",
}


def function_name(vba_name: str, taken: set[str]) -> str:
    name = vba_name if vba_name.lower() not in RESERVED else f"macro_{vba_name}"
    while name.lower() in taken:  # VBA names are case-blind; JavaScript's aren't
        name += "_"
    taken.add(name.lower())
    return name


@dataclass
class Macro:
    name: str  # as in Excel, shown in the Macros menu
    function: str = ""  # the Apps Script function it became
    lines: list[str] = field(default_factory=list)
    untranslated: int = 0
    statements: int = 0

    @property
    def complete(self) -> bool:
        return self.untranslated == 0


@dataclass
class Translation:
    macros: list[Macro]
    script: str
    # Code outside any Sub, or Subs taking arguments, events, functions: kept
    # as comments, never run.
    other_lines: int = 0

    def summary(self) -> dict:
        """Counts only, for the report: no names, no source."""
        return {
            "macros": len(self.macros),
            "fullyTranslated": sum(m.complete for m in self.macros),
            "partlyTranslated": sum(not m.complete for m in self.macros),
            "untranslatedLines": sum(m.untranslated for m in self.macros) + self.other_lines,
        }


def _js(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _vba_string(raw: str) -> str:
    return raw.replace('""', '"')


def _literal(expression: str) -> str | None:
    """A VBA constant as JavaScript, or None if it isn't one."""
    expression = expression.strip()
    if m := re.fullmatch(STRING, expression):
        return _js(_vba_string(m.group(1)))
    if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", expression):
        return expression
    if expression.lower() in {"true", "false"}:
        return expression.lower()
    return None


def _colour(expression: str) -> str | None:
    """A VBA colour (a number, BGR, or RGB(r, g, b)) as #rrggbb."""
    expression = expression.strip()
    if m := re.fullmatch(r"RGB\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*\)", expression, re.I):
        r, g, b = (min(int(x), 255) for x in m.groups())
        return f'"#{r:02x}{g:02x}{b:02x}"'
    if re.fullmatch(r"[0-9]+", expression) and int(expression) <= 0xFFFFFF:
        value = int(expression)
        return f'"#{value & 0xFF:02x}{(value >> 8) & 0xFF:02x}{(value >> 16) & 0xFF:02x}"'
    return None


def _address(text: str) -> str:
    return text.replace("$", "").upper()


class _Body:
    """One macro's statements, keeping the recorder's notion of 'selected'."""

    def __init__(self) -> None:
        self.out: list[str] = []
        self.copied: str | None = None
        # What is selected: whole "rows", whole "columns", or "cells". It
        # decides what a recorded Insert or Delete does.
        self.kind = "cells"

    def range_of(self, target: str, address: str | None) -> str:
        if target.lower() == "selection":
            return "selection"
        if target.lower() == "activecell":
            return "sheet.getActiveCell()"
        return f"sheet.getRange({_js(_address(address or ''))})"

    def emit(self, line: str) -> bool:
        """Writes `line`'s translation; False if it isn't one we know."""
        o = self.out
        if m := SHEET.match(line):
            o.append(f"sheet = book.getSheetByName({_js(_vba_string(m.group(1)))});")
            o.append("sheet.activate();")
            o.append("selection = sheet.getActiveRange();")
            self.kind = "unknown"  # whatever was selected on that sheet
        elif m := SELECT.match(line):
            o.append(f"selection = sheet.getRange({_js(_address(m.group(1)))});")
            self.kind = "cells"
        elif m := SELECT_ROWS.match(line):
            first, _, last = _address(m.group(1)).partition(":")
            o.append(f"selection = sheet.getRange({_js(f'{first}:{last or first}')});")
            self.kind = "rows"
        elif m := SELECT_COLUMNS.match(line):
            first, _, last = _address(m.group(1)).partition(":")
            o.append(f"selection = sheet.getRange({_js(f'{first}:{last or first}')});")
            self.kind = "columns"
        elif m := SELECT_CELL.match(line):
            o.append(f"selection = sheet.getRange({int(m.group(1))}, {int(m.group(2))});")
            self.kind = "cells"
        elif m := AUTOFILL.match(line):
            o.append(
                f"selection.autoFill(sheet.getRange({_js(_address(m.group(1)))}), "
                "SpreadsheetApp.AutoFillSeries.DEFAULT_SERIES);"
            )
        elif m := SET_FORMULA.match(line):
            where = self.range_of(m.group(1), m.group(2))
            setter = "setFormulaR1C1" if m.group(3).lower() == "formular1c1" else "setFormula"
            o.append(f"{where}.{setter}({_js(_vba_string(m.group(4)))});")
        elif (m := SET_VALUE.match(line)) and (value := _literal(m.group(4))) is not None:
            o.append(f"{self.range_of(m.group(1), m.group(2))}.setValue({value});")
        elif m := CLEAR.match(line):
            method = {
                "clearcontents": "clearContent",
                "clear": "clear",
                "clearformats": "clearFormat",
            }
            o.append(f"{self.range_of(m.group(1), m.group(2))}.{method[m.group(3).lower()]}();")
        elif m := COPY.match(line):
            self.copied = "copied"
            o.append(f"copied = {self.range_of(m.group(1), m.group(2))};")
        elif PASTE.match(line) and self.copied:
            o.append("copied.copyTo(selection);")
        elif (m := PASTE_SPECIAL.match(line)) and self.copied:
            kind = {
                "xlpastevalues": "PASTE_VALUES",
                "xlpasteformats": "PASTE_FORMAT",
                "xlpasteall": "PASTE_NORMAL",
            }[m.group(1).lower()]
            o.append(f"copied.copyTo(selection, SpreadsheetApp.CopyPasteType.{kind}, false);")
        elif (m := INSERT.match(line)) or (m := DELETE.match(line)):
            inserting = bool(INSERT.match(line))
            whole = (m.group(1) or "").lower()
            target = (
                "rows"
                if whole.startswith("entirerow")
                else "columns"
                if whole.startswith("entirecolumn")
                else self.kind
            )
            shift = (m.group(2) or "").lower()
            if target == "rows":
                verb = "insertRowsBefore" if inserting else "deleteRows"
                o.append(f"sheet.{verb}(selection.getRow(), selection.getNumRows());")
            elif target == "columns":
                verb = "insertColumnsBefore" if inserting else "deleteColumns"
                o.append(f"sheet.{verb}(selection.getColumn(), selection.getNumColumns());")
            elif target == "cells" and shift:
                # Cells shift as the macro says; with no direction Excel
                # guesses from the shape, so that is left for a person.
                dimension = "ROWS" if shift in {"xldown", "xlup"} else "COLUMNS"
                verb = "insertCells" if inserting else "deleteCells"
                o.append(f"selection.{verb}(SpreadsheetApp.Dimension.{dimension});")
            else:
                return False
        elif m := FONT.match(line):
            prop, value = m.group(1).lower(), m.group(2).strip()
            literal = _literal(value)
            if prop in {"bold", "italic", "underline"} and literal in {"true", "false"}:
                style = {
                    "bold": ("setFontWeight", '"bold"', '"normal"'),
                    "italic": ("setFontStyle", '"italic"', '"normal"'),
                    "underline": ("setFontLine", '"underline"', '"none"'),
                }[prop]
                o.append(f"selection.{style[0]}({style[1] if literal == 'true' else style[2]});")
            elif prop == "size" and literal and literal.replace(".", "", 1).isdigit():
                o.append(f"selection.setFontSize({literal});")
            elif prop == "name" and literal and literal.startswith('"'):
                o.append(f"selection.setFontFamily({literal});")
            elif prop == "color" and (colour := _colour(value)):
                o.append(f"selection.setFontColor({colour});")
            else:
                return False
        elif (m := FILL.match(line)) and (colour := _colour(m.group(1))):
            o.append(f"selection.setBackground({colour});")
        elif m := MSGBOX.match(line):
            o.append(f"SpreadsheetApp.getUi().alert({_js(_vba_string(m.group(1)))});")
        else:
            return False
        return True


def _logical_lines(source: str) -> list[str]:
    """Source lines with VBA's " _" continuations joined."""
    lines, pending = [], ""
    for raw in source.split("\n"):
        line = raw.rstrip()
        if line.endswith(" _"):
            pending += line[:-2] + " "
            continue
        lines.append(pending + line)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def _comment(line: str) -> str:
    return "  // Not translated: " + line.strip().replace("*/", "* /")


def translate(modules: list[Module]) -> Translation:
    macros: list[Macro] = []
    other: list[str] = []
    taken: set[str] = set()
    for module in modules:
        current: Macro | None = None
        body = _Body()
        for line in _logical_lines(module.source):
            text = line.strip()
            if (
                not text
                or text.startswith("'")
                or text.lower().startswith(("attribute ", "option "))
            ):
                continue
            if current is None:
                if (m := SUB.match(text)) and module.kind == "standard":
                    current = Macro(m.group(1), function_name(m.group(1), taken))
                    body = _Body()
                else:
                    other.append(f"{module.name}: {text}")
                continue
            if END_SUB.match(text):
                current.lines = body.out
                macros.append(current)
                current = None
                continue
            if NOISE.match(text):
                continue
            current.statements += 1
            if not body.emit(text):
                current.untranslated += 1
                body.out.append(_comment(text).strip())
        if current is not None:  # a Sub with no End Sub: keep what was read
            current.lines = body.out
            current.untranslated += 1
            macros.append(current)
    return Translation(macros, _script(macros, other), len(other))


HEADER = """\
/**
 * Macros from the original Excel workbook, written as Google Apps Script by
 * the Workspace Migration Toolkit.
 *
 * To use them: in the Google Sheet, choose Extensions > Apps Script, replace
 * what is there with this file, and save. Reload the Sheet: a "Macros" menu
 * appears. The first time a macro runs, Google asks you to allow it.
 *
 * Lines marked "Not translated" did nothing in Google and need doing by hand.
 */
"""


def _script(macros: list[Macro], other: list[str]) -> str:
    parts = [HEADER]
    if macros:
        menu = "\n".join(f"    .addItem({_js(m.name)}, {_js(m.function)})" for m in macros)
        parts.append(
            "function onOpen() {\n"
            '  SpreadsheetApp.getUi().createMenu("Macros")\n'
            f"{menu}\n"
            "    .addToUi();\n"
            "}\n"
        )
    for macro in macros:
        state = (
            "translated in full"
            if macro.complete
            else f"{macro.untranslated} line(s) not translated"
        )
        body = "\n".join("  " + line for line in macro.lines) or "  // (no steps)"
        parts.append(
            f"// {macro.name}: {state}.\n"
            f"function {macro.function}() {{\n"
            "  const book = SpreadsheetApp.getActiveSpreadsheet();\n"
            "  let sheet = book.getActiveSheet();\n"
            "  let selection = sheet.getActiveRange();\n"
            "  let copied = null;\n"
            f"{body}\n"
            "  selection.activate();\n"
            "}\n"
        )
    if other:
        parts.append(
            "// Code from the workbook that isn't a recorded macro, kept for reference:\n"
            + "\n".join("// " + line.replace("*/", "* /") for line in other)
            + "\n"
        )
    return "\n".join(parts)
