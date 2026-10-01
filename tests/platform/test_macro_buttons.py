"""A workbook's macro buttons, linked to their macros in Google.

The live test (2026-10-01): a workbook's "Repair Columns" button came across
as a drawing that did nothing, as Google keeps a shape but not what it ran,
and this workbook had lost the assignment in an earlier trip through Google.
Synthetic workbooks only; the linking script itself runs under Node against
a fake SpreadsheetApp.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import zipfile

import pytest
from workspace_toolkit.apps_script import translate
from workspace_toolkit.buttons import Button, _label_names, link, read_buttons
from workspace_toolkit.config import Settings
from workspace_toolkit.package import XLSM, Package
from workspace_toolkit.sheets import macro_notice
from workspace_toolkit.vba import Module
from workspace_toolkit.xlsx import analyse

from .test_vba_macros import REPAIR, macro_workbook

NODE = shutil.which("node")
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
TIDY = 'Attribute VB_Name = "Module2"\nSub Tidy()\n    Range("A1").Select\nEnd Sub\n'


def shape(label="", macro=None, col=23, row=1, kind="oneCellAnchor"):
    assigned = f' macro="{macro}"' if macro is not None else ""
    text = f"<xdr:txBody><a:p><a:r><a:t>{label}</a:t></a:r></a:p></xdr:txBody>" if label else ""
    return (
        f"<xdr:{kind}><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff>"
        f"<xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
        f'<xdr:sp{assigned}><xdr:nvSpPr><xdr:cNvPr id="3" name="Shape 3"/></xdr:nvSpPr>'
        f"{text}</xdr:sp><xdr:clientData/></xdr:{kind}>"
    )


def with_drawing(path, shapes="", vml=""):
    """Adds a drawing (and, if given, a legacy VML drawing) to sheet1."""
    with zipfile.ZipFile(path) as source:
        parts = {n: source.read(n) for n in source.namelist()}
    rels = []
    if shapes:
        parts["xl/drawings/drawing1.xml"] = (
            f'<xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}">{shapes}</xdr:wsDr>'
        ).encode()
        rels.append(f'<Relationship Id="d1" Type="{R}/drawing" Target="../drawings/drawing1.xml"/>')
    if vml:
        parts["xl/drawings/vmlDrawing1.vml"] = vml.encode()
        rels.append(
            f'<Relationship Id="v1" Type="{R}/vmlDrawing" Target="../drawings/vmlDrawing1.vml"/>'
        )
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    ).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return path


def workbook(tmp_path, sources=None, **drawing):
    path = macro_workbook(tmp_path / "book.xlsm", sources or {"Module1": ("standard", REPAIR)})
    return with_drawing(path, **drawing)


def found(path):
    package = Package(path, Settings(), XLSM)
    try:
        return read_buttons(package)
    finally:
        package.close()


def modules(*sources):
    return [Module(f"Module{i}", "standard", s) for i, s in enumerate(sources, start=1)]


# -------------------------------------------------------------------- reading


def test_the_repair_button_is_found_where_google_will_anchor_it(tmp_path):
    [button] = found(workbook(tmp_path, shapes=shape("Repair Columns"))).buttons
    # Excel counts from 0; Apps Script's getAnchorRow() from 1.
    assert button == Button("Class data", 2, 24, "Repair Columns", "")


def test_a_shape_with_neither_label_nor_macro_is_no_button(tmp_path):
    assert found(workbook(tmp_path, shapes=shape())).buttons == []


def test_form_control_buttons_are_counted_as_google_drops_them(tmp_path):
    vml = '<xml><v:shape><x:ClientData ObjectType="Button"/></v:shape></xml>'
    result = found(workbook(tmp_path, vml=vml))
    assert (result.buttons, result.form_buttons) == ([], 1)


# -------------------------------------------------------------------- matching


@pytest.mark.parametrize(
    ("label", "name", "names"),
    [
        ("Repair Columns", "Repair", True),
        ("Repair Columns", "RepairColumns", True),
        ("repair", "Repair", True),
        ("Repairs", "Repair", False),
        ("Rep", "Repair", False),
        ("Run Repair", "Repair", False),
        ("", "Repair", False),
    ],
)
def test_a_label_names_a_macro_only_in_whole_words_from_its_start(label, name, names):
    assert _label_names(label, name) is names


def test_a_button_with_no_macro_runs_the_only_macro_its_label_names():
    links, missed = link([Button("S", 2, 24, "Repair Columns", "")], [("Repair", "Repair")])
    assert [(k.function, k.by) for k in links] == [("Repair", "label")]
    assert missed == 0


def test_with_two_macros_a_label_alone_links_nothing_and_counts_nothing():
    # It may be only a text box: never guessed at, never reported.
    macros = [("Repair", "Repair"), ("Tidy", "Tidy")]
    assert link([Button("S", 2, 24, "Repair Columns", "")], macros) == ([], 0)


@pytest.mark.parametrize("assigned", ["[0]!Tidy", "[0]!Module2.Tidy", "'book.xlsm'!Tidy", "tidy"])
def test_an_assigned_macro_wins_over_the_label(assigned):
    macros = [("Repair", "Repair"), ("Tidy", "Tidy")]
    links, _ = link([Button("S", 2, 24, "Repair Columns", assigned)], macros)
    assert [(k.function, k.by) for k in links] == [("Tidy", "assigned")]


def test_an_assigned_macro_that_isnt_there_is_counted_unlinked():
    assert link([Button("S", 2, 24, "Go", "[0]!Missing")], [("Repair", "Repair")]) == ([], 1)


def test_a_button_runs_the_macros_renamed_function():
    links, _ = link([Button("S", 1, 1, "", "Delete")], [("Delete", "macro_Delete")])
    assert links[0].function == "macro_Delete"


# -------------------------------------------------------------------- scripts


def test_both_scripts_link_the_buttons_when_the_sheet_opens():
    t = translate(modules(REPAIR), [Button("Class data", 2, 24, "Repair Columns", "")])
    assert t.summary()["linkedButtons"] == 1
    for script in (t.script, t.bound_script):
        assert "function onOpen() {\n  linkButtons_();" in script
        assert '"macro": "Repair"' in script and '"row": 2, "column": 24' in script
    assert "createMenu" in t.script and "createMenu" not in t.bound_script


def test_a_workbook_without_buttons_keeps_its_scripts_as_they_were():
    plain, linked = translate(modules(REPAIR)), translate(modules(REPAIR), [])
    assert plain.bound_script == linked.bound_script
    assert "onOpen" not in plain.bound_script and "linkButtons_" not in plain.script


def test_a_macro_named_like_the_linker_cant_replace_it():
    source = REPAIR.replace("Repair", "linkButtons_")
    [macro] = translate(modules(source)).macros
    assert macro.function != "linkButtons_"


SHEET_HARNESS = r"""
const script = require('fs').readFileSync(0, 'utf8');
const drawings = JSON.parse(process.argv[1]);
const made = drawings.map(([row, column, action]) => ({
  action, getOnAction() { return this.action; }, setOnAction(a) { this.action = a; },
  getContainerInfo: () => ({ getAnchorRow: () => row, getAnchorColumn: () => column }),
}));
const sheet = { getName: () => 'Class data', getDrawings: () => made };
const SpreadsheetApp = { getActiveSpreadsheet: () => ({ getSheets: () => [sheet] }) };
const console = { warn() {} };
eval(script + '\nonOpen();');
process.stdout.write(JSON.stringify(made.map(d => d.action)));
"""


def opened(script: str, drawings: list) -> list:
    done = subprocess.run(  # noqa: S603  # nosec B603 -- fixed argv, no shell
        [str(NODE), "-e", SHEET_HARNESS, json.dumps(drawings)],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="needs Node to run the script")
@pytest.mark.parametrize(
    ("drawings", "actions"),
    [
        # The only drawing on the sheet, even if Google anchored it a cell over.
        ([[2, 25, ""]], ["Repair"]),
        # Several drawings: only the one at the button's anchor.
        ([[1, 1, ""], [2, 24, ""]], ["", "Repair"]),
        ([[1, 1, ""], [5, 5, ""]], ["", ""]),
        # One the person has linked already stays theirs.
        ([[2, 24, "Mine"]], ["Mine"]),
    ],
)
def test_opening_the_sheet_links_the_button(drawings, actions):
    bound = translate(
        modules(REPAIR), [Button("Class data", 2, 24, "Repair Columns", "")]
    ).bound_script
    assert opened(bound, drawings) == actions


# -------------------------------------------------------------------- report


def test_the_report_counts_buttons_and_gives_no_labels(tmp_path):
    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    source = with_drawing(
        macro_workbook(root / "source.xlsm", {"Module1": ("standard", REPAIR)}),
        shapes=shape("Repair Columns") + shape("Go", macro="[0]!Missing", col=1),
    )
    manifest = analyse(source, root / "result")
    assert manifest["macroCode"]["linkedButtons"] == 1
    assert manifest["macroCode"]["unlinkedButtons"] == 1
    codes = {w["code"] for w in manifest["warnings"]}
    assert {"macro_buttons_linked", "macro_buttons_not_linked"} <= codes
    text = (root / "result" / "manifest.json").read_text(encoding="utf-8")
    assert "Repair Columns" not in text  # counts only; sheet names are listed already
    bound = (root / "result" / "macros" / "apps-script-bound.gs").read_text(encoding="utf-8")
    assert '"macro": "Repair"' in bound


@pytest.mark.parametrize(("count", "said"), [(1, "Its button works too."), (2, "Its buttons")])
def test_the_page_says_the_buttons_work(count, said):
    report = {
        "appsScript": {"attached": True},
        "warnings": [
            {"code": "macros_attached"},
            {"code": "macro_buttons_linked", "buttonCount": count},
        ],
    }
    assert said in (macro_notice(report) or "")


def test_the_page_says_nothing_of_buttons_when_there_are_none():
    report = {"appsScript": {"attached": True}, "warnings": [{"code": "macros_attached"}]}
    assert "button" not in (macro_notice(report) or "x")
