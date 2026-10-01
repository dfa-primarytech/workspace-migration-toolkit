"""Macro workbooks convert, with their macros saved and written as Apps Script.

A nursery workbook's one macro, "Repair", was recorded in Excel: it fills
three blocks of formulas back down from row 12 to 161. Its workbook was
refused for having macros at all, and Google turned out to convert no .xlsm
in any case (live test, 2026-10-01). The macro projects here are built in
Microsoft's published formats ([MS-CFB], [MS-OVBA]), so the reader is tested
on the same structures as a real file, without any real file's contents.
"""

from __future__ import annotations

import asyncio
import json
import struct
import zipfile

import pytest
from workspace_toolkit.apps_script import translate
from workspace_toolkit.config import Settings
from workspace_toolkit.macros import UPLOADED, macro_free
from workspace_toolkit.package import XLSM, XLSX, Package
from workspace_toolkit.sheets import convert
from workspace_toolkit.vba import Module, VbaUnreadable, decompress, read_modules
from workspace_toolkit.xlsx import analyse

from .test_xlsx import workbook_parts
from .test_xlsx_issue51 import RecordingGoogle

FREE, END, FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD


# --------------------------------------------------------------- building one


def compress(data: bytes) -> bytes:
    """[MS-OVBA] 2.4.1, literals only: valid, if not small."""
    out = bytearray(b"\x01")
    for start in range(0, len(data), 3640):  # literals fit a chunk up to here
        chunk = data[start : start + 3640]
        body = bytearray()
        for i in range(0, len(chunk), 8):
            body.append(0)
            body += chunk[i : i + 8]
        out += struct.pack("<H", ((len(body) + 2 - 3) & 0x0FFF) | 0xB000) + body
    return bytes(out)


def record(rid: int, body: bytes) -> bytes:
    return struct.pack("<HI", rid, len(body)) + body


def dir_stream(modules: list[tuple[str, str, int]]) -> bytes:
    """A dir stream: a project version record (whose size field lies), then
    each module's name, stream, offset and type."""
    out = record(0x0001, struct.pack("<I", 1))  # PROJECTSYSKIND
    out += struct.pack("<HI", 0x0009, 4) + b"\x00" * 6  # PROJECTVERSION: 6 bytes, not 4
    for name, kind, offset in modules:
        out += record(0x0019, name.encode())
        out += record(0x001A, name.encode()) + record(0x0032, name.encode("utf-16-le"))
        out += record(0x0031, struct.pack("<I", offset))
        out += record(0x0021 if kind == "standard" else 0x0022, b"")
        out += record(0x002B, b"")
    return out + record(0x0010, b"")


def compound(streams: dict[str, bytes]) -> bytes:
    """[MS-CFB] v3 with a root, a VBA storage and its streams, all small
    enough for the mini stream, as Office writes them."""
    names = list(streams)
    mini, minifat, starts = bytearray(), [], {}
    for name in names:
        data = streams[name]
        starts[name] = len(mini) // 64
        count = max(1, -(-len(data) // 64))
        minifat += [starts[name] + i + 1 for i in range(count - 1)] + [END]
        mini += data.ljust(count * 64, b"\x00")
    mini_sectors = -(-len(mini) // 512)
    minifat_bytes = struct.pack(f"<{len(minifat)}I", *minifat).ljust(512, b"\xff")

    def entry(name, kind, child=FREE, right=FREE, start=END, size=0):
        encoded = (name + "\0").encode("utf-16-le")
        raw = encoded.ljust(64, b"\x00") + struct.pack("<HBB", len(encoded), kind, 1)
        raw += struct.pack("<III", FREE, right, child) + b"\x00" * 36
        return raw + struct.pack("<IQ", start, size)

    # sector 0: FAT, 1-2: directory, 3: mini FAT, 4..: mini stream
    entries = [entry("Root Entry", 5, child=1, start=4, size=len(mini)), entry("VBA", 1, child=2)]
    for i, name in enumerate(names):
        right = 3 + i if i + 1 < len(names) else FREE
        entries.append(entry(name, 2, right=right, start=starts[name], size=len(streams[name])))
    directory = b"".join(entries).ljust(1024, b"\x00")
    fat = [FATSECT, 2, END, END] + [5 + i for i in range(mini_sectors - 1)] + [END]
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHH", header, 24, 0x3E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<IIII", header, 44, 1, 1, 0, 4096)
    struct.pack_into("<IIII", header, 60, 3, 1, END, 0)
    struct.pack_into("<109I", header, 76, 0, *[FREE] * 108)
    sectors = struct.pack(f"<{len(fat)}I", *fat).ljust(512, b"\xff") + directory + minifat_bytes
    return bytes(header) + sectors + bytes(mini).ljust(mini_sectors * 512, b"\x00")


def project(sources: dict[str, tuple[str, str]]) -> bytes:
    """A vbaProject.bin: module name -> (kind, source)."""
    streams, listed = {}, []
    for name, (kind, source) in sources.items():
        cache = b"\xcc" * 7  # a module stream starts with its compiled form
        streams[name] = cache + compress(source.replace("\n", "\r\n").encode("cp1252"))
        listed.append((name, kind, len(cache)))
    return compound({"dir": compress(dir_stream(listed)), **streams})


REPAIR = """Attribute VB_Name = "Module1"
Sub Repair()
Attribute Repair.VB_ProcData.VB_Invoke_Func = " \\n14"
'
' Repair Macro
'
    Range("C12:D12").Select
    Selection.AutoFill Destination:=Range("C12:D161"), Type:=xlFillDefault
    ActiveWindow.ScrollRow = 146
    ActiveWindow.SmallScroll Down:=-134
    Range("t12:w12").Select
    Selection.AutoFill Destination:=Range("t12:w161"), Type:=xlFillDefault
    ActiveWindow.ScrollColumn = 35
    Range("A13").Select
End Sub
"""


def macro_workbook(path, sources):
    parts = workbook_parts(suffix=".xlsm")
    parts["xl/vbaProject.bin"] = project(sources)
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        "</Relationships>",
        '<Relationship Id="vba" Type="http://schemas.microsoft.com/office/2006/relationships/'
        'vbaProject" Target="vbaProject.bin"/></Relationships>',
    )
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>",
        '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>',
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return path


# -------------------------------------------------------------------- reading


def test_a_macro_project_is_read_module_by_module():
    modules = read_modules(
        project({"Module1": ("standard", REPAIR), "Sheet1": ("document", "Attribute VB_Name")})
    )
    assert [(m.name, m.kind) for m in modules] == [("Module1", "standard"), ("Sheet1", "document")]
    assert "Sub Repair()" in modules[0].source and "\r" not in modules[0].source


def test_a_raw_chunk_is_read_as_it_is():
    data = bytes(range(256)) * 16  # 4096 bytes
    assert decompress(b"\x01" + struct.pack("<H", 0x3FFF) + data) == data


@pytest.mark.parametrize(
    "damage",
    [
        b"not a compound file at all" * 30,
        project({"Module1": ("standard", REPAIR)})[:700],  # cut short
        project({"Module1": ("standard", REPAIR)}).replace(b"\x01", b"\x02", 1),
    ],
)
def test_a_damaged_project_is_unreadable_not_a_crash(damage):
    with pytest.raises(VbaUnreadable):
        read_modules(damage)


def test_a_copy_token_reaching_before_its_chunk_is_refused():
    token = struct.pack("<H", 0xFFFF)
    with pytest.raises(VbaUnreadable):
        decompress(b"\x01" + struct.pack("<H", 0xB000 | 2) + b"\x02A" + token)


# --------------------------------------------------------------- translating


def script_of(source: str, kind: str = "standard"):
    return translate([Module("Module1", kind, source)])


def test_the_recorded_repair_macro_is_translated_in_full():
    t = script_of(REPAIR)
    assert t.summary() == {
        "macros": 1,
        "fullyTranslated": 1,
        "partlyTranslated": 0,
        "untranslatedLines": 0,
        "linkedButtons": 0,
        "unlinkedButtons": 0,
    }
    assert 'selection = sheet.getRange("C12:D12");' in t.script
    assert (
        'selection.autoFill(sheet.getRange("T12:W161"), '
        "SpreadsheetApp.AutoFillSeries.DEFAULT_SERIES);" in t.script
    )
    assert "Scroll" not in t.script  # window-only steps are dropped
    assert '.addItem("Repair", "Repair")' in t.script


def test_the_recorders_other_steps_are_translated():
    source = """Sub Tidy()
    Sheets("Autumn Term").Select
    Range("A1").Select
    ActiveCell.FormulaR1C1 = "=SUM(R[1]C:R[10]C)"
    Range("B2").Value = "Done"
    Range("B3").Value = 42
    Range("A1:C1").Select
    Selection.Font.Bold = True
    Selection.Interior.Color = 65535
    Selection.Font.Color = RGB(255, 0, 0)
    Range("D5").Select
    Selection.ClearContents
    Range("A2:A9").Select
    Selection.Copy
    Range("E2").Select
    Selection.PasteSpecial Paste:=xlPasteValues, Operation:=xlNone
    Application.CutCopyMode = False
    Rows("4:4").Select
    Selection.Insert Shift:=xlDown
    Columns("F:F").Select
    Selection.Delete Shift:=xlToLeft
    MsgBox "All tidy"
End Sub
"""
    t = script_of(source)
    assert t.summary()["untranslatedLines"] == 0, t.script
    for expected in [
        'sheet = book.getSheetByName("Autumn Term");',
        'sheet.getActiveCell().setFormulaR1C1("=SUM(R[1]C:R[10]C)");',
        'sheet.getRange("B2").setValue("Done");',
        'sheet.getRange("B3").setValue(42);',
        'selection.setFontWeight("bold");',
        'selection.setBackground("#ffff00");',  # 65535 is BGR for yellow
        'selection.setFontColor("#ff0000");',
        "selection.clearContent();",
        "copied.copyTo(selection, SpreadsheetApp.CopyPasteType.PASTE_VALUES, false);",
        "sheet.insertRowsBefore(selection.getRow(), selection.getNumRows());",
        "sheet.deleteColumns(selection.getColumn(), selection.getNumColumns());",
        'SpreadsheetApp.getUi().alert("All tidy");',
    ]:
        assert expected in t.script, expected


def test_code_that_isnt_recorded_is_kept_as_comments_not_guessed():
    source = """Sub Count()
    Dim i As Integer
    For i = 1 To 10
        Cells(i, 1).Value = i
    Next i
    Range("A1").Select
End Sub
Function Twice(x)
    Twice = x * 2
End Function
"""
    t = script_of(source)
    assert t.summary() == {
        "macros": 1,
        "fullyTranslated": 0,
        "partlyTranslated": 1,
        "untranslatedLines": 7,
        "linkedButtons": 0,
        "unlinkedButtons": 0,
    }
    assert "// Not translated: For i = 1 To 10" in t.script
    assert "// Module1: Function Twice(x)" in t.script  # outside any Sub: for reference
    assert 'selection = sheet.getRange("A1");' in t.script


def test_a_macro_named_like_a_javascript_word_still_loads():
    t = translate(
        [Module("Module1", "standard", "Sub Delete()\nEnd Sub\nSub delete_()\nEnd Sub\n")]
    )
    assert "function macro_Delete()" in t.script
    assert '.addItem("Delete", "macro_Delete")' in t.script


def test_event_code_in_a_sheet_module_is_not_made_a_menu_macro():
    t = script_of("Private Sub Worksheet_Change(ByVal Target As Range)\nEnd Sub\n", "document")
    assert t.macros == [] and t.other_lines == 2
    assert "onOpen" not in t.script


def test_a_comment_ender_in_vba_cant_close_the_scripts_comment():
    t = script_of('Sub A()\n    DoSomething "*/ alert(1) /*"\nEnd Sub\n')
    assert "*/ alert" not in t.script


# ------------------------------------------------------------- the workbook


def test_an_xlsm_is_written_again_as_a_plain_xlsx(tmp_path):
    source = macro_workbook(tmp_path / "book.xlsm", {"Module1": ("standard", REPAIR)})
    package = Package(source, Settings(), XLSM)
    try:
        macro_free(package, tmp_path / "book.xlsx", Settings())
    finally:
        package.close()
    with zipfile.ZipFile(tmp_path / "book.xlsx") as out, zipfile.ZipFile(source) as original:
        assert not [n for n in out.namelist() if "vba" in n.lower()]
        types = out.read("[Content_Types].xml")
        assert b"vbaProject" not in types and b"macroEnabled" not in types
        assert b"vbaProject" not in out.read("xl/_rels/workbook.xml.rels")
        sheet = "xl/worksheets/sheet1.xml"
        assert out.read(sheet) == original.read(sheet)  # the content is untouched
    Package(tmp_path / "book.xlsx", Settings(), XLSX).close()


def analysed(tmp_path, sources):
    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    source = macro_workbook(root / "source.xlsm", sources)
    return root, analyse(source, root / "result")


def test_the_macros_are_saved_and_only_counted_in_the_manifest(tmp_path):
    root, manifest = analysed(tmp_path, {"Module1": ("standard", REPAIR)})
    saved = root / "result" / "macros"
    assert "Sub Repair()" in (saved / "original-vba.txt").read_text(encoding="utf-8")
    assert "function Repair()" in (saved / "apps-script.txt").read_text(encoding="utf-8")
    assert manifest["macroCode"]["fullyTranslated"] == 1
    text = (root / "result" / "manifest.json").read_text(encoding="utf-8")
    assert "Repair" not in text and "AutoFill" not in text
    assert "macros_translated" in {w["code"] for w in manifest["warnings"]}


def test_a_macro_workbook_converts_with_its_macros_in_the_folder(tmp_path):
    root, manifest = analysed(tmp_path, {"Module1": ("standard", REPAIR)})
    google = RecordingGoogle()
    report = asyncio.run(convert(root, manifest, google))
    assert report["status"] == "converted_with_review"
    sent = {upload[1]: upload for upload in google.uploads}
    assert sent["Original workbook.xlsm"][2] == XLSM.mime
    imported = [u for u in google.uploads if u[4].get("convert")]
    assert [(u[0], u[2]) for u in imported] == [("converted.xlsx", XLSX.mime)]
    for name in UPLOADED.values():
        assert sent[name][2] == "text/plain"
    assert [o["name"] for o in report["assetOutputs"]] == list(UPLOADED.values())
    [note] = [w for w in report["warnings"] if w["code"] == "macros_translated"]
    assert "Extensions → Apps Script" in note["message"]
    assert "AutoFill" not in json.dumps(report) and "Repair" not in json.dumps(report)


def test_a_partly_translated_macro_says_how_much_is_left(tmp_path):
    source = 'Sub Odd()\n    Range("A1").Select\n    Calculate\nEnd Sub\n'
    _, manifest = analysed(tmp_path, {"Module1": ("standard", source)})
    [note] = [w for w in manifest["warnings"] if w["code"] == "macros_partly_translated"]
    assert note["untranslatedLines"] == 1
    assert "1 line couldn't be" in note["message"]


@pytest.mark.parametrize(
    "selected, step, expected",
    [
        ('Rows("4:6").Select', "Selection.Delete Shift:=xlUp", "sheet.deleteRows("),
        ('Columns("F:F").Select', "Selection.Delete Shift:=xlToLeft", "sheet.deleteColumns("),
        ('Range("B2").Select', "Selection.EntireRow.Insert", "sheet.insertRowsBefore("),
        (
            'Range("B2:C3").Select',
            "Selection.Insert Shift:=xlDown",
            "selection.insertCells(SpreadsheetApp.Dimension.ROWS);",
        ),
        (
            'Range("B2:C3").Select',
            "Selection.Delete Shift:=xlToLeft",
            "selection.deleteCells(SpreadsheetApp.Dimension.COLUMNS);",
        ),
    ],
)
def test_insert_and_delete_follow_what_is_selected(selected, step, expected):
    # A recorded Delete after selecting whole columns deletes those columns,
    # not rows: what was selected decides it, as in Excel.
    t = script_of(f"Sub A()\n    {selected}\n    {step}\nEnd Sub\n")
    assert t.summary()["untranslatedLines"] == 0
    assert expected in t.script


def test_cells_inserted_without_a_direction_are_left_for_a_person():
    t = script_of('Sub A()\n    Range("B2:C3").Select\n    Selection.Insert\nEnd Sub\n')
    assert t.summary()["untranslatedLines"] == 1
    assert "// Not translated: Selection.Insert" in t.script
