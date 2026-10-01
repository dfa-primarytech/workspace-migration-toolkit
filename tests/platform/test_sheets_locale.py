"""A converted Sheet reads dates the UK way, in the person's own time zone.

A nursery calculator typed its children's dates of birth as text,
"31/07/2023". UK Excel reads that as 31 July; a Google Sheet in a US locale
reads no date at all, and all 84 formulas built on them gave #VALUE! (live
test, 2026-10-01). Every converted Sheet is now given the UK locale, and the
report counts the dates typed as text.
"""

from __future__ import annotations

import asyncio
import json
import zipfile

import pytest
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.pipelines import resolve
from workspace_toolkit.sheets import convert
from workspace_toolkit.web import time_zone
from workspace_toolkit.xlsx import NS, analyse

from .test_xlsx import workbook_parts, write_workbook
from .test_xlsx_issue51 import RecordingGoogle


def dated_workbook(path):
    """Text dates: two shared, one inline; and lookalikes that aren't."""
    parts = workbook_parts(suffix=path.suffix)
    parts["xl/sharedStrings.xml"] = (
        f'<sst xmlns="{NS["x"]}"><si><t>DOB</t></si><si><t>31/07/2023</t></si>'
        "<si><t>1.9.25</t></si><si><t>Room 3/4</t></si></sst>"
    )
    parts["xl/worksheets/sheet1.xml"] = (
        f'<worksheet xmlns="{NS["x"]}"><dimension ref="A1:B4"/><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>1</v></c></row>'
        '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3" t="s"><v>3</v></c></row>'
        '<row r="4"><c r="A4" t="inlineStr"><is><t>07-31-2023</t></is></c>'
        # A formula's text result is the formula's business, not a typed date.
        '<c r="B4" t="str"><f>TEXT(A2,"dd/mm/yyyy")</f><v>31/07/2023</v></c></row>'
        "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return path


def test_dates_typed_as_text_are_counted_without_their_text(tmp_path):
    manifest = analyse(dated_workbook(tmp_path / "source.xlsx"), tmp_path / "result")
    assert manifest["inventory"]["textDates"] == 4
    [note] = [w for w in manifest["warnings"] if w["code"] == "dates_stored_as_text"]
    assert note["cellCount"] == 4 and note["sheets"] == [0]
    assert "4 dates are typed as text" in note["message"]
    saved = (tmp_path / "result" / "manifest.json").read_text(encoding="utf-8")
    assert "31/07/2023" not in saved and "1.9.25" not in saved


def test_a_workbook_without_text_dates_gets_no_such_note(tmp_path):
    manifest = analyse(write_workbook(tmp_path / "source.xlsx"), tmp_path / "result")
    assert manifest["inventory"]["textDates"] == 0
    assert "dates_stored_as_text" not in {w["code"] for w in manifest["warnings"]}


class SettingsGoogle(RecordingGoogle):
    """Records the Sheet's settings; refuses the time zones in `refuse`."""

    def __init__(self, refuse=()):
        super().__init__()
        self.refuse, self.settings = set(refuse), []

    async def request(self, method, url, **kwargs):
        if url.endswith(":batchUpdate"):
            props = kwargs["json"]["requests"][0]["updateSpreadsheetProperties"]["properties"]
            self.settings.append(props)
            if props["timeZone"] in self.refuse:
                raise ToolkitError("google_failed", "refused", 502)
            return {}
        return await super().request(method, url, **kwargs)


def converted(tmp_path, google, **options):
    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    source = dated_workbook(root / "source.xlsx")
    manifest = analyse(source, root / "result")
    return asyncio.run(convert(root, manifest, google, **options))


def test_the_sheet_is_given_the_uk_locale_and_the_persons_time_zone(tmp_path):
    google = SettingsGoogle()
    report = converted(tmp_path, google, time_zone="America/New_York")
    assert google.settings == [{"locale": "en_GB", "timeZone": "America/New_York"}]
    assert report["spreadsheetSettings"] == {"locale": "en_GB", "timeZone": "America/New_York"}
    assert report["status"] == "converted_with_review"


def test_without_a_time_zone_the_sheet_is_set_to_london(tmp_path):
    google = SettingsGoogle()
    converted(tmp_path, google)
    assert google.settings == [{"locale": "en_GB", "timeZone": "Europe/London"}]


def test_a_time_zone_google_refuses_falls_back_to_london(tmp_path):
    google = SettingsGoogle(refuse={"Mars/Olympus_Mons"})
    report = converted(tmp_path, google, time_zone="Mars/Olympus_Mons")
    assert [s["timeZone"] for s in google.settings] == ["Mars/Olympus_Mons", "Europe/London"]
    assert report["spreadsheetSettings"]["timeZone"] == "Europe/London"


def test_a_sheet_whose_settings_cant_be_set_still_converts_and_says_so(tmp_path):
    google = SettingsGoogle(refuse={"Europe/London"})
    report = converted(tmp_path, google)
    assert report["status"] == "converted_with_review" and report.get("spreadsheetId")
    assert "locale_not_set" in {w["code"] for w in report["warnings"]}
    assert "spreadsheetSettings" not in report


def test_a_workbook_kept_for_moving_by_hand_says_why(tmp_path):
    # The page used to say "Converted." for these, with nothing to open.
    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    manifest = analyse(write_workbook(root / "source.xlsm"), root / "result")
    report = asyncio.run(convert(root, manifest, SettingsGoogle()))
    assert report["status"] == "manual_migration_required"
    assert report["stoppedBecause"].startswith("Not converted: it has macros")
    assert "url" not in report


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Europe/London", "Europe/London"),
        ("America/Argentina/Buenos_Aires", "America/Argentina/Buenos_Aires"),
        ("Etc/GMT+5", "Etc/GMT+5"),
        ("UTC", "UTC"),
        (None, None),
        ("", None),
        ("Europe/London; DROP", None),
        ("../../etc/passwd", None),
        ("A/" * 40 + "B", None),
    ],
)
def test_only_a_time_zone_shaped_header_is_used(header, expected):
    assert time_zone(header) == expected


def test_only_spreadsheets_are_given_a_time_zone():
    assert resolve("x.xlsx").needs_time_zone and resolve("x.xlsm").needs_time_zone
    assert not resolve("x.pptx").needs_time_zone and not resolve("x.docx").needs_time_zone


def test_the_report_holds_no_cell_text(tmp_path):
    report = converted(tmp_path, SettingsGoogle())
    assert "31/07/2023" not in json.dumps(report)
