from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from starlette.responses import Response

from .config import Settings
from .errors import ToolkitError

SCOPE = "https://www.googleapis.com/auth/drive.file"
SESSION = "wmt_session"
STATE = "wmt_oauth"


class Auth:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.box = Fernet(settings.session_key.encode()) if settings.session_key else None

    def seal(self, data: dict) -> str:
        if self.box is None:
            raise ToolkitError("auth_unconfigured", "Google sign-in has not been configured.", 503)
        token = self.box.encrypt(json.dumps(data).encode()).decode()
        if len(token) > 3800:
            raise ToolkitError("session_limit", "Google sign-in could not be completed.", 502)
        return token

    def open(self, token: str | None, ttl: int) -> dict:
        if not token or self.box is None:
            raise ToolkitError("sign_in_required", "Please sign in with Google.", 401)
        try:
            return json.loads(self.box.decrypt(token.encode(), ttl=ttl))
        except (InvalidToken, ValueError, TypeError) as exc:
            raise ToolkitError(
                "session_expired", "Your session has expired. Please sign in again.", 401
            ) from exc

    def cookie(self, response: Response, name: str, data: dict, ttl: int) -> None:
        response.set_cookie(
            name,
            self.seal(data),
            max_age=ttl,
            httponly=True,
            secure=self.settings.secure_cookies,
            samesite="lax",
            path="/",
        )

    def start(self) -> tuple[str, dict]:
        if not self.settings.oauth_ready:
            raise ToolkitError("auth_unconfigured", "Google sign-in has not been configured.", 503)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        query = urlencode(
            {
                "client_id": self.settings.client_id,
                "redirect_uri": self.settings.redirect_uri,
                "response_type": "code",
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "online",
            }
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + query, {
            "state": state,
            "verifier": verifier,
        }

    async def exchange(
        self, code: str, state: str, cookie: str | None, client: httpx.AsyncClient
    ) -> dict:
        expected = self.open(cookie, 600)
        if not state or not hmac.compare_digest(state, expected.get("state", "")):
            raise ToolkitError(
                "invalid_state", "Google sign-in could not be verified. Please try again.", 400
            )
        try:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "redirect_uri": self.settings.redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": expected["verifier"],
                },
            )
            response.raise_for_status()
            token = response.json()
            if (
                SCOPE not in token.get("scope", "").split()
                or token.get("token_type", "").lower() != "bearer"
            ):
                raise ValueError("Required permission missing")
            expires = min(int(token["expires_in"]), 3600)
            if expires <= 0:
                raise ValueError("Expired token")
            return {
                "access_token": token["access_token"],
                "expires": int(time.time()) + expires,
                "csrf": secrets.token_urlsafe(32),
            }
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ToolkitError(
                "oauth_failed", "Google sign-in failed. Please try again.", 502
            ) from exc

    def session(self, request: Request, *, csrf: bool = False) -> dict:
        data = self.open(request.cookies.get(SESSION), 3600)
        if data.get("expires", 0) <= time.time():
            raise ToolkitError(
                "session_expired", "Your session has expired. Please sign in again.", 401
            )
        if csrf:
            origin = request.headers.get("origin")
            if origin and origin != self.settings.base_url:
                raise ToolkitError("csrf_failed", "This request could not be verified.", 403)
            sent = request.headers.get("x-csrf-token", "")
            if not sent or not hmac.compare_digest(sent, data.get("csrf", "")):
                raise ToolkitError("csrf_failed", "This request could not be verified.", 403)
        return data
