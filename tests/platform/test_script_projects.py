"""A converted workbook's macros are added to its new Sheet, when allowed.

Pasting a script into the Apps Script editor is too much to ask of most
teachers (owner, 2026-10-01). When the person allowed it at sign-in, the app
creates a script bound to the Sheet and puts the translated macros in it, so
the Macros menu is simply there. Without that permission, the Apps Script API
is never called, and the macros stay in the folder to paste in.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from workspace_toolkit.auth import SCOPE, SCRIPT_SCOPE, Auth
from workspace_toolkit.script_projects import SCRIPT_SCOPES, attach
from workspace_toolkit.sheets import convert

from .test_vba_macros import REPAIR, analysed
from .test_web import configured
from .test_xlsx_issue51 import RecordingGoogle


def exchanged(granted: str) -> dict:
    auth = Auth(configured())
    _, state = auth.start()
    reply = {"access_token": "t", "token_type": "Bearer", "scope": granted, "expires_in": 3600}

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=reply))
        async with httpx.AsyncClient(transport=transport) as client:
            return await auth.exchange("code", state["state"], auth.seal(state), client)

    return asyncio.run(run())


def test_the_session_remembers_whether_apps_script_was_allowed():
    assert exchanged(f"{SCOPE} {SCRIPT_SCOPE}")["scripts"] is True
    # Google lets a person untick it; signing in still works.
    assert exchanged(SCOPE)["scripts"] is False


class ScriptGoogle(RecordingGoogle):
    """The app's Google, with the Apps Script API behind `answer`."""

    def __init__(self, answer):
        super().__init__()
        self.answer, self.calls = answer, []
        self.headers = {"Authorization": "Bearer t"}

    def handler(self, request):
        self.calls.append((request.method, request.url.path, request.content))
        return self.answer(request)


def converted(tmp_path, google, allowed):
    root, manifest = analysed(tmp_path, {"Module1": ("standard", REPAIR)})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(google.handler)) as client:
            google.client = client
            return await convert(root, manifest, google, attach_macros=allowed)

    return asyncio.run(run())


def google_says(create=200, fill=200, message=""):
    def answer(request):
        if request.method == "POST":
            if create != 200:
                return httpx.Response(create, json={"error": {"message": message}})
            return httpx.Response(200, json={"scriptId": "script-1"})
        return httpx.Response(fill, json={} if fill == 200 else {"error": {"message": message}})

    return answer


def test_allowed_the_macros_are_put_in_the_sheet(tmp_path):
    google = ScriptGoogle(google_says())
    report = converted(tmp_path, google, allowed=True)
    created, filled = google.calls
    assert created[:2] == ("POST", "/v1/projects")
    assert json.loads(created[2])["parentId"] == report["spreadsheetId"]
    files = {f["name"]: f for f in json.loads(filled[2])["files"]}
    assert "function Repair()" in files["Macros"]["source"]
    scopes = json.loads(files["appsscript"]["source"])["oauthScopes"]
    assert scopes == SCRIPT_SCOPES  # this one spreadsheet and its menus, not Drive
    assert report["appsScript"] == {"attached": True, "scriptId": "script-1"}
    codes = {w["code"] for w in report["warnings"]}
    assert "macros_attached" in codes and "macros_translated" not in codes
    [note] = [w for w in report["warnings"] if w["code"] == "macros_attached"]
    assert "Extensions → Macros" in note["message"] and "paste" not in note["message"]
    # The paste-in copy stays in the folder all the same.
    assert "Macros for Google Sheets (Apps Script).txt" in {
        o["name"] for o in report["assetOutputs"]
    }


def test_not_allowed_the_apps_script_api_is_never_called(tmp_path):
    google = ScriptGoogle(google_says())
    report = converted(tmp_path, google, allowed=False)
    assert google.calls == []
    assert report["appsScript"] == {"attached": False, "reason": "not_allowed"}
    assert "macros_translated" in {w["code"] for w in report["warnings"]}  # paste-in note


def test_a_person_with_the_setting_off_is_told_where_to_turn_it_on(tmp_path):
    google = ScriptGoogle(
        google_says(create=403, message="User has not enabled the Apps Script API. Enable it")
    )
    report = converted(tmp_path, google, allowed=True)
    assert report["status"] == "converted_with_review"  # the Sheet itself is fine
    assert report["appsScript"]["reason"] == "setting_off"
    [note] = [w for w in report["warnings"] if w["code"] == "macros_not_attached"]
    assert "script.google.com/home/usersettings" in note["message"]
    assert "macros_translated" in {w["code"] for w in report["warnings"]}


@pytest.mark.parametrize("create, fill", [(500, 200), (200, 500), (403, 200)])
def test_any_other_refusal_leaves_the_paste_in_route(tmp_path, create, fill):
    report = converted(tmp_path, ScriptGoogle(google_says(create=create, fill=fill)), True)
    assert report["status"] == "converted_with_review"
    assert report["appsScript"]["attached"] is False
    assert "macros_not_attached" in {w["code"] for w in report["warnings"]}


def test_a_workbook_without_macros_creates_no_script(tmp_path):
    from workspace_toolkit.xlsx import analyse

    from .test_xlsx import write_workbook

    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    manifest = analyse(write_workbook(root / "source.xlsx"), root / "result")
    google = ScriptGoogle(google_says())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(google.handler)) as client:
            google.client = client
            return await convert(root, manifest, google, attach_macros=True)

    report = asyncio.run(run())
    assert google.calls == [] and "appsScript" not in report


def test_the_script_holds_no_more_than_the_macros(tmp_path):
    google = ScriptGoogle(google_says())
    converted(tmp_path, google, allowed=True)
    names = {f["name"] for f in json.loads(google.calls[1][2])["files"]}
    assert names == {"appsscript", "Macros"}


def test_attach_reports_a_project_left_empty_as_failed():
    async def run():
        transport = httpx.MockTransport(google_says(fill=500))
        async with httpx.AsyncClient(transport=transport) as client:
            return await attach(client, {}, "sheet", "title", "code", "Europe/London")

    result = asyncio.run(run())
    assert result.script_id is None and result.reason == "failed"


def test_attached_macros_are_google_sheets_macros_under_extensions(tmp_path):
    # Declared in the manifest, each one is listed under Extensions > Macros,
    # where Google Sheets keeps its own macros, with no extra menu.
    google = ScriptGoogle(google_says())
    converted(tmp_path, google, allowed=True)
    files = {f["name"]: f for f in json.loads(google.calls[1][2])["files"]}
    settings = json.loads(files["appsscript"]["source"])
    assert settings["sheets"]["macros"] == [{"menuName": "Repair", "functionName": "Repair"}]
    assert "createMenu" not in files["Macros"]["source"]
    assert "function Repair()" in files["Macros"]["source"]


@pytest.mark.parametrize(
    "allowed, answer, expected",
    [
        (True, google_says(), "find them under Extensions → Macros"),
        (True, google_says(), "Google will ask you to approve it"),
        (
            True,
            google_says(create=403, message="User has not enabled the Apps Script API. Enable it"),
            "turn on the Apps Script API (https://script.google.com/home/usersettings)",
        ),
        (False, google_says(), "sign out, sign in again and allow Apps Script"),
    ],
)
def test_the_page_is_told_what_happened_to_the_macros(tmp_path, allowed, answer, expected):
    # The one note shown on screen: the person may need to approve them, or
    # find them in the folder (owner, 2026-10-01).
    report = converted(tmp_path, ScriptGoogle(answer), allowed=allowed)
    assert report["notice"].startswith("This workbook uses macros.")
    assert expected in report["notice"]


def test_a_workbook_without_macros_gets_no_notice(tmp_path):
    from workspace_toolkit.xlsx import analyse

    from .test_xlsx import write_workbook

    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    manifest = analyse(write_workbook(root / "source.xlsx"), root / "result")
    report = asyncio.run(convert(root, manifest, ScriptGoogle(google_says())))
    assert "notice" not in report


def test_macros_that_couldnt_be_read_are_still_mentioned(tmp_path):
    from workspace_toolkit.xlsx import analyse

    from .test_xlsx import write_workbook

    root = tmp_path / "job"
    (root / "result").mkdir(parents=True)
    manifest = analyse(write_workbook(root / "source.xlsm"), root / "result")  # fake project
    report = asyncio.run(convert(root, manifest, ScriptGoogle(google_says())))
    assert "couldn't be converted automatically" in report["notice"]
