from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 25 * 1024 * 1024
    max_expanded_bytes: int = 200 * 1024 * 1024
    max_entry_bytes: int = 50 * 1024 * 1024
    max_xml_bytes: int = 8 * 1024 * 1024
    # Elements in one XML part, counted while it is parsed. Word writes about
    # 38 bytes of XML per element, so an 8 MiB part holds about 220,000 and
    # max_xml_bytes is the limit a real document meets first. This one only
    # catches markup far denser than any Office application writes -- which
    # would otherwise cost about 350 bytes of memory per element. Raise the
    # two together (issues #36 and #46).
    max_xml_elements: int = 500_000
    max_entries: int = 5000
    max_compression_ratio: int = 200
    parser_timeout: int = 30
    job_timeout: int = 240
    temp_dir: str | None = None
    base_url: str = "http://localhost:8080"
    client_id: str = ""
    client_secret: str = ""
    session_key: str = ""

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def oauth_ready(self) -> bool:
        return bool(self.client_id and self.client_secret and self.session_key)

    @property
    def redirect_uri(self) -> str:
        return self.base_url + "/auth/callback"

    @classmethod
    def from_env(cls) -> Settings:
        base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
        url = urlsplit(base)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.path
            or url.query
            or url.fragment
            or url.username
        ):
            raise ValueError("PUBLIC_BASE_URL must be an origin")
        if url.scheme != "https" and url.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("HTTPS is required outside localhost")
        limit = int(os.getenv("MAX_UPLOAD_SIZE", str(25 * 1024 * 1024)))
        if limit <= 0 or limit > 100 * 1024 * 1024:
            raise ValueError("MAX_UPLOAD_SIZE must be between 1 and 104857600 bytes")
        return cls(
            max_upload_bytes=limit,
            base_url=base,
            temp_dir=os.getenv("TEMP_DIR"),
            client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            session_key=os.getenv("SESSION_ENCRYPTION_KEY", ""),
        )
