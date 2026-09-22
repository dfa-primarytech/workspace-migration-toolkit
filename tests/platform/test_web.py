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
