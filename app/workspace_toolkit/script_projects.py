"""Adds a converted workbook's macros to its new Google Sheet (DECISIONS.md, 2026-10-01).

The one place the app talks to the Apps Script API. It creates a script
project bound to the Sheet the app has just made, and puts the translated
macros in it (apps_script.py), so the Macros menu is there when the person
opens the Sheet. Nothing is run here.

It only happens when the person allowed it at sign-in (auth.SCRIPT_SCOPE),
and the script asks only for the one spreadsheet it sits in and its menus,
not the person's Drive. Google can still refuse: most often because the
person hasn't turned on the Apps Script API in their own settings. Then the
caller says how to, and the macros stay in the folder to paste in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

SCRIPT_API = "https://script.googleapis.com/v1/projects"
SETTINGS_URL = "https://script.google.com/home/usersettings"
# What the macros may touch: this spreadsheet, and its menus and alerts.
SCRIPT_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.currentonly",
    "https://www.googleapis.com/auth/script.container.ui",
]


@dataclass
class Attached:
    script_id: str | None = None
    # Why not: "setting_off" (the person's Apps Script API setting),
    # "not_allowed" (no permission), or "failed".
    reason: str | None = None


def manifest(time_zone: str) -> str:
    return json.dumps(
        {
            "timeZone": time_zone,
            "runtimeVersion": "V8",
            "exceptionLogging": "STACKDRIVER",
            "oauthScopes": SCRIPT_SCOPES,
        },
        indent=2,
    )


def _why(response: httpx.Response) -> str:
    text = response.text.lower()
    if response.status_code == 403 and "apps script api" in text and "enable" in text:
        return "setting_off"
    if response.status_code in {401, 403}:
        return "not_allowed"
    return "failed"


async def attach(
    client: httpx.AsyncClient,
    headers: dict,
    spreadsheet_id: str,
    title: str,
    script: str,
    time_zone: str,
) -> Attached:
    """Creates the bound project and fills it. A project made but left
    empty is reported as failed: an empty project does no harm, and making
    another on a retry would be worse."""
    try:
        made = await client.post(
            SCRIPT_API, headers=headers, json={"title": title, "parentId": spreadsheet_id}
        )
        if made.status_code != 200:
            return Attached(reason=_why(made))
        script_id = made.json().get("scriptId")
        if not isinstance(script_id, str) or not script_id:
            return Attached(reason="failed")
        filled = await client.put(
            f"{SCRIPT_API}/{script_id}/content",
            headers=headers,
            json={
                "files": [
                    {"name": "appsscript", "type": "JSON", "source": manifest(time_zone)},
                    {"name": "Macros", "type": "SERVER_JS", "source": script},
                ]
            },
        )
        if filled.status_code != 200:
            return Attached(reason=_why(filled))
        return Attached(script_id=script_id)
    except (httpx.HTTPError, ValueError):
        return Attached(reason="failed")
