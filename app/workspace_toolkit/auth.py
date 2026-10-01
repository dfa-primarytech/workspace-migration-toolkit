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
# Optional: lets the app add a converted workbook's macros to its new Sheet
# (DECISIONS.md, 2026-10-01). Someone who unticks it still converts; the
# macros are then left in the folder to paste in.
SCRIPT_SCOPE = "https://www.googleapis.com/auth/script.projects"
# Asked for only when sign-in is limited to some domains: who is signing in.
IDENTITY_SCOPE = "openid email"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
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
            data = json.loads(self.box.decrypt(token.encode(), ttl=ttl))
            if not isinstance(data, dict):
                raise ValueError("Invalid session payload")
            return data
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
                "scope": f"{SCOPE} {SCRIPT_SCOPE}"
                + (f" {IDENTITY_SCOPE}" if self.settings.allowed_domains else ""),
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
            granted = token.get("scope", "").split()
            if SCOPE not in granted or token.get("token_type", "").lower() != "bearer":
                raise ValueError("Required permission missing")
            if self.settings.allowed_domains:
                self.check_account(token.get("id_token"))
            expires = min(int(token["expires_in"]), 3600)
            access_token = token.get("access_token")
            if expires <= 0 or not isinstance(access_token, str) or not access_token:
                raise ValueError("Expired token")
            return {
                "access_token": access_token,
                "expires": int(time.time()) + expires,
                "csrf": secrets.token_urlsafe(32),
                "scripts": SCRIPT_SCOPE in granted,
            }
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise ToolkitError(
                "oauth_failed", "Google sign-in failed. Please try again.", 502
            ) from exc

    def check_account(self, id_token: object) -> None:
        """Refuses anyone but a Workspace account on an allowed domain.

        The ID token came straight from Google's token endpoint over TLS,
        in exchange for this app's own code and secret, so its claims are
        read without checking its signature (OpenID Connect Core 3.1.3.7).
        A damaged one is a failed sign-in (ValueError); a well-formed one
        for someone else is a refusal. Nothing about the person is kept.
        """
        if not isinstance(id_token, str) or id_token.count(".") != 2:
            raise ValueError("No ID token")
        body = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if (
            not isinstance(claims, dict)
            or claims.get("iss") not in ISSUERS
            or claims.get("aud") != self.settings.client_id
            or float(claims.get("exp", 0)) <= time.time()
        ):
            raise ValueError("ID token not for this app")
        email = claims.get("email")
        domain = email.rsplit("@", 1)[-1].lower() if isinstance(email, str) else ""
        # hd is set only for a Google Workspace account: a personal Google
        # account made with a school address has none.
        if (
            claims.get("email_verified") is not True
            or not claims.get("hd")
            or domain not in self.settings.allowed_domains
        ):
            raise ToolkitError(
                "account_not_allowed",
                "This converter is for staff. Sign in with your school staff account.",
                403,
            )

    def session(self, request: Request, *, csrf: bool = False) -> dict:
        data = self.open(request.cookies.get(SESSION), 3600)
        try:
            expires = float(data.get("expires", 0))
        except (TypeError, ValueError):
            expires = 0
        if (
            expires <= time.time()
            or not isinstance(data.get("access_token"), str)
            or not data["access_token"]
            or not isinstance(data.get("csrf"), str)
            or not data["csrf"]
        ):
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
