"""Handing pictures to Google Slides through short-lived Cloud Storage links.

Slides' `createImage` fetches a picture from "a publicly accessible URL",
with no exception for Drive files, and Google's own guide recommends a
Cloud Storage signed URL (DECISIONS.md, 2026-09-28). So each picture is
uploaded to a private bucket, signed for 15 minutes, fetched once by Slides,
and deleted as soon as its page is built. A one-day lifecycle rule on the
bucket is the backstop for anything a crash leaves behind.

No key files. The app acts as its own service account:

- on Cloud Run, with a token from the metadata server;
- anywhere else (a developer's machine), with the application-default
  credentials `gcloud auth application-default login` writes;
- or, for a test run on a machine that should hold nothing lasting, a
  one-hour token for the signing service account itself, minted elsewhere
  (`PUBLISHER_STORAGE_TOKEN`; docs/publisher-storage.md).

Links are signed by Google, through the IAM Credentials `signBlob` call. The
account needs the Service Account Token Creator role on the signing service
account; see docs/publisher-storage.md.

These credentials are never the signed-in person's. Their token stays
`drive.file`-scoped and never reaches the bucket.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from .errors import ToolkitError

HOST = "storage.googleapis.com"
METADATA = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105  # nosec B105 -- an endpoint
IAM = "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{}:signBlob"
LINK_SECONDS = 15 * 60  # Google's guide: signed URLs that expire in 15 minutes
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}
SIGNED = re.compile(r"https://storage\.googleapis\.com/\S*X-Goog-Signature=[0-9a-f]+\S*")


def failed(message: str, exc: BaseException | None = None) -> ToolkitError:
    detail = ""
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"HTTP {exc.response.status_code}"
    elif exc is not None:
        detail = type(exc).__name__
    return ToolkitError("picture_delivery_failed", message, 502, detail=detail)


def scrub(text: str) -> str:
    """Signed links are credentials while they last: never report one."""
    return SIGNED.sub("[signed link]", text)


# ------------------------------------------------------------------ credentials


class Credentials:
    """An access token for the app's own Google account, refreshed as needed."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self._token = ""  # nosec B105 -- no token yet, fetched on first use
        self._expires = 0.0

    async def token(self) -> str:
        if time.time() > self._expires - 60:
            self._token, lifetime = await self._fetch()
            self._expires = time.time() + lifetime
        return self._token

    async def _fetch(self) -> tuple[str, float]:
        raise NotImplementedError


class MetadataCredentials(Credentials):
    """The service account a Cloud Run service runs as."""

    async def _fetch(self) -> tuple[str, float]:
        response = await self.client.get(METADATA + "/token", headers={"Metadata-Flavor": "Google"})
        response.raise_for_status()
        body = response.json()
        return body["access_token"], float(body.get("expires_in", 300))

    async def email(self) -> str:
        response = await self.client.get(METADATA + "/email", headers={"Metadata-Flavor": "Google"})
        response.raise_for_status()
        return response.text.strip()


class StaticCredentials(Credentials):
    """A token minted elsewhere for the signing account. It expires within the
    hour and nothing here can renew it: when Google refuses it, pictures fail
    plainly rather than falling back to anything broader."""

    def __init__(self, client: httpx.AsyncClient, token: str):
        super().__init__(client)
        self.value = token

    async def _fetch(self) -> tuple[str, float]:
        return self.value, 3600.0


class UserCredentials(Credentials):
    """`gcloud auth application-default login`, for running the app locally."""

    def __init__(self, client: httpx.AsyncClient, info: dict):
        super().__init__(client)
        self.info = info

    async def _fetch(self) -> tuple[str, float]:
        response = await self.client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.info["client_id"],
                "client_secret": self.info["client_secret"],
                "refresh_token": self.info["refresh_token"],
            },
        )
        response.raise_for_status()
        body = response.json()
        return body["access_token"], float(body.get("expires_in", 300))


def default_credentials_file() -> Path:
    explicit = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if explicit:
        return Path(explicit)
    if os.name == "nt" and os.getenv("APPDATA"):
        return Path(os.environ["APPDATA"]) / "gcloud" / "application_default_credentials.json"
    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def credentials(client: httpx.AsyncClient) -> Credentials:
    """Cloud Run's service account there; a developer's own login elsewhere."""
    if os.getenv("K_SERVICE"):  # set by Cloud Run
        return MetadataCredentials(client)
    token = os.getenv("PUBLISHER_STORAGE_TOKEN", "").strip()
    if token:
        return StaticCredentials(client, token)
    path = default_credentials_file()
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ToolkitError(
            "publisher_storage_unavailable",
            "This server has no Google Cloud credentials for handing pictures to Slides.",
            503,
        ) from None
    if info.get("type") != "authorized_user":
        # A downloaded service-account key is a long-lived secret on disk:
        # not something this app will read (docs/publisher-storage.md).
        raise ToolkitError(
            "publisher_storage_unavailable",
            "Only Cloud Run's own account or a gcloud login can be used for pictures.",
            503,
        )
    return UserCredentials(client, info)


# ------------------------------------------------------------------ signing


def _encode(text: str, safe: str = "") -> str:
    return quote(text, safe="-_.~" + safe)


def canonical(
    bucket: str, name: str, signer: str, when: datetime, seconds: int
) -> tuple[str, str, str]:
    """The V4 canonical request, string to sign, and query, for a GET."""
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{when:%Y%m%d}/auto/storage/goog4_request"
    query = "&".join(
        f"{key}={_encode(value)}"
        for key, value in sorted(
            {
                "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
                "X-Goog-Credential": f"{signer}/{scope}",
                "X-Goog-Date": stamp,
                "X-Goog-Expires": str(seconds),
                "X-Goog-SignedHeaders": "host",
            }.items()
        )
    )
    path = f"/{_encode(bucket)}/{_encode(name, safe='/')}"
    request = "\n".join(["GET", path, query, f"host:{HOST}", "", "host", "UNSIGNED-PAYLOAD"])
    digest = hashlib.sha256(request.encode()).hexdigest()
    to_sign = "\n".join(["GOOG4-RSA-SHA256", stamp, scope, digest])
    return request, to_sign, query


class Bucket:
    """Uploads, signs and deletes the pictures for one conversion."""

    def __init__(self, name: str, signer: str, creds: Credentials, client: httpx.AsyncClient):
        self.name = name
        self.signer = signer
        self.creds = creds
        self.client = client

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + await self.creds.token()}

    async def upload(self, path: Path, mime: str) -> str:
        """Stores a copy under a random name that says nothing about the document."""
        name = f"publisher/{uuid.uuid4().hex}{EXTENSIONS.get(mime, '')}"
        try:
            response = await self.client.post(
                f"https://{HOST}/upload/storage/v1/b/{_encode(self.name)}/o",
                params={"uploadType": "media", "name": name, "ifGenerationMatch": "0"},
                headers={**await self._headers(), "Content-Type": mime},
                content=path.read_bytes(),
            )
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            raise failed("A picture could not be stored for Google Slides to fetch.", exc) from exc
        return name

    async def sign(
        self, name: str, seconds: int = LINK_SECONDS, now: datetime | None = None
    ) -> str:
        _, to_sign, query = canonical(
            self.name, name, self.signer, now or datetime.now(UTC), seconds
        )
        try:
            response = await self.client.post(
                IAM.format(_encode(self.signer, safe="@")),
                headers=await self._headers(),
                json={"payload": base64.b64encode(to_sign.encode()).decode()},
            )
            response.raise_for_status()
            signature = base64.b64decode(response.json()["signedBlob"]).hex()
        except (httpx.HTTPError, KeyError, ValueError, binascii.Error) as exc:
            raise failed("A picture's link for Google Slides could not be signed.", exc) from exc
        path = f"/{_encode(self.name)}/{_encode(name, safe='/')}"
        return f"https://{HOST}{path}?{query}&X-Goog-Signature={signature}"

    async def delete(self, name: str) -> bool:
        """True once the copy is gone. Never raises: the lifecycle rule is the backstop."""
        try:
            response = await self.client.delete(
                f"https://{HOST}/storage/v1/b/{_encode(self.name)}/o/{_encode(name)}",
                headers=await self._headers(),
            )
            return response.status_code in {200, 204, 404}
        except httpx.HTTPError:
            return False
