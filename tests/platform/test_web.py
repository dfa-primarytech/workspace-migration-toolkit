import asyncio
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from workspace_toolkit.auth import SCOPE, SESSION, Auth
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.package import PPTX_MIME
from workspace_toolkit.web import create_app


def configured(**kwargs):
    return Settings(
        client_id="test-client",
        client_secret="test-secret",  # pragma: allowlist secret -- synthetic fixture
        session_key=Fernet.generate_key().decode(),
        **kwargs,
    )


def signed_client(settings):
    app = create_app(settings)
    client = TestClient(app, base_url=settings.base_url)
    data = {"access_token": "not-a-real-token", "expires": time.time() + 3600, "csrf": "test-csrf"}
    client.cookies.set(SESSION, app.state.auth.seal(data))
    return client


def test_oauth_state_and_pkce():
    auth = Auth(configured())
    url, state = auth.start()
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == [SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert state["verifier"] not in url
    assert "test-secret" not in url
    assert "not-a-real-token" not in auth.seal({"access_token": "not-a-real-token"})


def test_auth_rejects_tampering_and_expiry():
    auth = Auth(configured())
    token = auth.seal({"value": 1})
    with pytest.raises(ToolkitError):
        auth.open(token[:-10] + "tampered", 600)
    expired = auth.box.encrypt_at_time(b"{}", int(time.time()) - 700).decode()
    with pytest.raises(ToolkitError):
        auth.open(expired, 600)
    invalid_shape = auth.box.encrypt(b"[]").decode()
    with pytest.raises(ToolkitError):
        auth.open(invalid_shape, 600)


@pytest.mark.parametrize(
    "session_data",
    [
        {"access_token": "", "expires": 9999999999, "csrf": "csrf"},
        {"access_token": "token", "expires": "invalid", "csrf": "csrf"},
        {"access_token": "token", "expires": 9999999999, "csrf": 123},
    ],
)
def test_invalid_session_payload_is_rejected(session_data):
    settings = configured()
    app = create_app(settings)
    client = TestClient(app, base_url=settings.base_url)
    client.cookies.set(SESSION, app.state.auth.seal(session_data))
    assert client.get("/api/session").json()["signedIn"] is False


def test_oauth_wrong_state_never_contacts_google():
    auth = Auth(configured())
    _, state = auth.start()

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: pytest.fail("contacted Google"))
        ) as client:
            with pytest.raises(ToolkitError, match="verified"):
                await auth.exchange("code", "wrong", auth.seal(state), client)

    asyncio.run(run())


def test_oauth_exchange():
    auth = Auth(configured())
    _, state = auth.start()

    def handler(request):
        assert b"code_verifier=" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "fake-access",
                "token_type": "Bearer",
                "scope": SCOPE,
                "expires_in": 3600,
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await auth.exchange("code", state["state"], auth.seal(state), client)

    result = asyncio.run(run())
    assert result["access_token"] == "fake-access"
    assert result["csrf"]


@pytest.mark.parametrize("access_token", [None, "", 123])
def test_oauth_rejects_invalid_access_token(access_token):
    auth = Auth(configured())
    _, state = auth.start()

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "access_token": access_token,
                        "token_type": "Bearer",
                        "scope": SCOPE,
                        "expires_in": 3600,
                    },
                )
            )
        ) as client:
            with pytest.raises(ToolkitError) as error:
                await auth.exchange("code", state["state"], auth.seal(state), client)
            assert error.value.code == "oauth_failed"

    asyncio.run(run())


def test_secure_cookie_headers():
    settings = configured(base_url="https://example.test")
    client = TestClient(create_app(settings), base_url=settings.base_url)
    response = client.get("/auth/start", follow_redirects=False)
    assert response.status_code == 302
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert response.headers["referrer-policy"] == "no-referrer"


def test_web_auth_csrf_and_host(pptx):
    settings = configured()
    client = TestClient(create_app(settings), base_url=settings.base_url)
    assert client.post("/api/analyse").status_code == 401
    client = signed_client(settings)
    assert client.post("/api/analyse").status_code == 403
    assert (
        client.post(
            "/api/analyse", headers={"X-CSRF-Token": "test-csrf", "Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert client.get("/healthz", headers={"Host": "evil.invalid"}).status_code == 400


def test_web_preflight_cleanup_and_hash_guard(pptx, tmp_path):
    work = tmp_path / "jobs"
    work.mkdir()
    settings = configured(temp_dir=str(work))
    client = signed_client(settings)
    headers = {
        "Content-Type": PPTX_MIME,
        "X-Upload-Filename": "sample.pptx",
        "X-CSRF-Token": "test-csrf",
    }
    response = client.post("/api/analyse", content=pptx.read_bytes(), headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["pages"] == 2
    assert not list(work.iterdir())
    response = client.post("/api/convert", content=pptx.read_bytes(), headers=headers)
    assert response.status_code == 409
    assert not list(work.iterdir())


def test_upload_stream_limit(tmp_path):
    client = signed_client(configured(max_upload_bytes=5, temp_dir=str(tmp_path)))
    response = client.post(
        "/api/analyse",
        content=iter([b"123", b"456"]),
        headers={
            "Content-Type": PPTX_MIME,
            "X-Upload-Filename": "x.pptx",
            "X-CSRF-Token": "test-csrf",
        },
    )
    assert response.status_code == 413
    assert not list(tmp_path.iterdir())


def test_no_stacktrace_or_credentials_on_unexpected_error(monkeypatch, pptx):
    async def failure(*args):
        raise RuntimeError("private document text and secret")

    monkeypatch.setattr("workspace_toolkit.web.preflight", failure)
    client = signed_client(configured())
    response = client.post(
        "/api/analyse",
        content=pptx.read_bytes(),
        headers={
            "Content-Type": PPTX_MIME,
            "X-Upload-Filename": "x.pptx",
            "X-CSRF-Token": "test-csrf",
        },
    )
    assert response.status_code == 500
    assert "private" not in response.text and "RuntimeError" not in response.text


def test_plaintext_nonlocal_configuration_rejected(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        Settings.from_env()


def test_convert_refuses_a_sign_in_that_would_expire_mid_job(pptx):
    # Issue #52: a token with a few minutes left was accepted, and ran out
    # partway through the uploads.
    settings = configured()
    app = create_app(settings)
    client = TestClient(app, base_url=settings.base_url)
    data = {
        "access_token": "not-a-real-token",
        "expires": time.time() + settings.job_timeout - 30,
        "csrf": "test-csrf",
    }
    client.cookies.set(SESSION, app.state.auth.seal(data))
    headers = {
        "Content-Type": PPTX_MIME,
        "X-Upload-Filename": "sample.pptx",
        "X-CSRF-Token": "test-csrf",
    }
    response = client.post("/api/convert", content=pptx.read_bytes(), headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expiring"
    # Checking a file needs no Google access, so it still works.
    assert (
        client.post("/api/analyse", content=pptx.read_bytes(), headers=headers).status_code == 200
    )


def test_what_happened_in_drive_reaches_the_report(monkeypatch, pptx):
    """Issue #70: a duplicate library folder is reported whichever format ran."""
    from dataclasses import replace

    from workspace_toolkit import web
    from workspace_toolkit.pipelines import resolve

    async def analysed(root, settings, fmt):
        return {"source": {"sha256": "abc"}}

    async def converted(root, manifest, google, progress, original_name=""):
        google.warnings.append({"code": "library_duplicated", "message": "two folders"})
        return {"status": "completed", "warnings": [{"code": "own"}]}

    pipeline = replace(resolve("x.pptx"), convert=converted)
    monkeypatch.setattr(web, "preflight", analysed)
    monkeypatch.setattr(web, "resolve", lambda name: pipeline)
    client = signed_client(configured())
    response = client.post(
        "/api/convert",
        content=pptx.read_bytes(),
        headers={
            "Content-Type": PPTX_MIME,
            "X-Upload-Filename": "x.pptx",
            "X-CSRF-Token": "test-csrf",
            "X-Source-SHA256": "abc",
        },
    )
    assert response.status_code == 200, response.text
    assert [w["code"] for w in response.json()["warnings"]] == ["own", "library_duplicated"]


def test_session_advertises_picker_availability():
    signed_in = signed_client(configured(picker_api_key="test-picker-key"))
    body = signed_in.get("/api/session").json()
    assert body["pickerEnabled"] is True
    assert body["pickerApiKey"] == "test-picker-key"
    not_configured = signed_client(configured())
    body = not_configured.get("/api/session").json()
    assert body["pickerEnabled"] is False
    assert body["pickerApiKey"] == ""


def test_picker_token_route_is_unavailable_without_configuration():
    client = signed_client(configured())
    response = client.get("/api/picker-token")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "picker_unavailable"


def test_picker_token_route_returns_the_session_access_token():
    client = signed_client(configured(picker_api_key="test-picker-key"))
    response = client.get("/api/picker-token")
    assert response.status_code == 200
    assert response.json() == {"accessToken": "not-a-real-token"}


def test_a_drive_file_id_is_refused_when_picker_is_not_configured():
    client = signed_client(configured())
    response = client.post(
        "/api/analyse",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Upload-Filename": "x.pptx",
            "X-CSRF-Token": "test-csrf",
            "X-Drive-File-Id": "drive123",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "picker_unavailable"


def test_convert_downloads_a_drive_picked_file_instead_of_the_request_body(monkeypatch, pptx):
    """A Drive pick sends no body at all -- the server fetches the bytes
    itself by id (see Google.download), so nothing about the source ever
    passes through the browser twice."""
    from dataclasses import replace

    from workspace_toolkit import web
    from workspace_toolkit.pipelines import resolve

    seen = {}

    async def fake_download(self, file_id, destination, max_bytes):
        seen["file_id"] = file_id
        seen["max_bytes"] = max_bytes
        destination.write_bytes(pptx.read_bytes())
        return destination.stat().st_size

    async def analysed(root, settings, fmt):
        return {"source": {"sha256": "abc"}}

    async def converted(root, manifest, google, progress, original_name=""):
        return {"status": "completed"}

    pipeline = replace(resolve("x.pptx"), convert=converted)
    monkeypatch.setattr(web.Google, "download", fake_download)
    monkeypatch.setattr(web, "preflight", analysed)
    monkeypatch.setattr(web, "resolve", lambda name: pipeline)
    client = signed_client(configured(picker_api_key="test-picker-key"))
    response = client.post(
        "/api/convert",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Upload-Filename": "x.pptx",
            "X-CSRF-Token": "test-csrf",
            "X-Drive-File-Id": "drive123",
            "X-Source-SHA256": "abc",
        },
    )
    assert response.status_code == 200, response.text
    assert seen["file_id"] == "drive123"


def test_an_empty_drive_file_is_refused_the_same_way_as_an_empty_upload(monkeypatch):
    from workspace_toolkit import web
    from workspace_toolkit.pipelines import resolve

    async def fake_download(self, file_id, destination, max_bytes):
        destination.touch()
        return 0

    monkeypatch.setattr(web.Google, "download", fake_download)
    monkeypatch.setattr(web, "resolve", lambda name: resolve("x.pptx"))
    client = signed_client(configured(picker_api_key="test-picker-key"))
    response = client.post(
        "/api/analyse",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Upload-Filename": "x.pptx",
            "X-CSRF-Token": "test-csrf",
            "X-Drive-File-Id": "drive123",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_upload"
