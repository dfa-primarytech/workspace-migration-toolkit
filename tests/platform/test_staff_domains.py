"""Sign-in limited to staff domains (ALLOWED_DOMAINS).

The hosted app is for one trust's staff: their school domains, not the
student. ones, and no personal Google accounts. Unset, anyone Google lets
sign in may (the test host). Synthetic domains only.
"""

import asyncio
import base64
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from workspace_toolkit.auth import SCOPE, Auth
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.web import create_app

from .test_web import configured

STAFF = frozenset({"school.example", "trust.example"})


def id_token(**claims):
    body = {
        "iss": "https://accounts.google.com",
        "aud": "test-client",
        "exp": time.time() + 600,
        "email": "teacher@school.example",
        "email_verified": True,
        "hd": "trust.example",
        **claims,
    }
    part = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    return f"e30.{part}.signature"


def exchange(settings, token):
    auth = Auth(settings)
    _, state = auth.start()
    reply = {"access_token": "a", "token_type": "Bearer", "scope": SCOPE, "expires_in": 3600}
    if token is not None:
        reply["id_token"] = token

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=reply))
        async with httpx.AsyncClient(transport=transport) as client:
            return await auth.exchange("code", state["state"], auth.seal(state), client)

    return asyncio.run(run())


def refused(token):
    with pytest.raises(ToolkitError) as error:
        exchange(configured(allowed_domains=STAFF), token)
    return error.value.code


def test_staff_on_an_allowed_domain_sign_in():
    assert exchange(configured(allowed_domains=STAFF), id_token())["access_token"] == "a"


def test_the_address_case_does_not_matter():
    assert exchange(configured(allowed_domains=STAFF), id_token(email="T@School.Example"))


@pytest.mark.parametrize(
    "claims",
    [
        {"email": "pupil@student.school.example"},  # a student domain is not its school's
        {"email": "someone@elsewhere.example"},
        {"hd": None},  # a personal Google account made with a school address
        {"email_verified": False},
        {"email_verified": "true"},
    ],
)
def test_anyone_else_is_refused(claims):
    assert refused(id_token(**claims)) == "account_not_allowed"


@pytest.mark.parametrize(
    "token",
    [
        None,
        "not-a-jwt",
        "e30.!!!.sig",
        id_token(aud="another-app"),
        id_token(iss="https://evil.example"),
        id_token(exp=time.time() - 1),
        id_token(exp={"x": 1}),
    ],
)
def test_a_missing_or_foreign_id_token_is_a_failed_sign_in(token):
    assert refused(token) == "oauth_failed"


def test_without_a_list_no_identity_is_asked_or_checked():
    settings = configured()
    url, _ = Auth(settings).start()
    assert "openid" not in parse_qs(urlsplit(url).query)["scope"][0]
    assert exchange(settings, None)["access_token"] == "a"


def test_with_a_list_the_email_address_is_asked_for():
    url, _ = Auth(configured(allowed_domains=STAFF)).start()
    assert parse_qs(urlsplit(url).query)["scope"][0].endswith(" openid email")


def test_nothing_about_the_person_is_kept_in_the_session():
    data = exchange(configured(allowed_domains=STAFF), id_token())
    assert "school.example" not in json.dumps(data)


def test_a_refused_account_goes_back_to_the_page_with_a_reason(monkeypatch):
    settings = configured(allowed_domains=STAFF)
    app = create_app(settings)
    client = TestClient(app, base_url=settings.base_url)

    async def refuse(*_):
        raise ToolkitError("account_not_allowed", "staff only", 403)

    monkeypatch.setattr(app.state.auth, "exchange", refuse)
    response = client.get("/auth/callback?code=c&state=s", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/?signin=not_allowed"


def test_the_list_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_DOMAINS", " School.example, @trust.example  other.example ")
    assert Settings.from_env().allowed_domains == {
        "school.example",
        "trust.example",
        "other.example",
    }
