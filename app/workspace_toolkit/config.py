from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    # No upload limit unless a deployment sets MAX_UPLOAD_SIZE (issue #36).
    # What a file can safely expand to is bounded below instead, in
    # proportion to the file itself.
    max_upload_bytes: int | None = None
    # Zip-bomb guards. Each is a floor, raised in proportion to the actual
    # file: one part may expand to entry_scale x the file, the whole package
    # to expanded_scale x. Real media barely compresses, so a real file never
    # meets these; a crafted small file still meets the floor, as before.
    max_expanded_bytes: int = 200 * 1024 * 1024
    max_entry_bytes: int = 50 * 1024 * 1024
    entry_scale: int = 2
    expanded_scale: int = 3
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
    # Base allowances, extended by file size. Measured analysis on Linux runs
    # at about 30 MiB/s; 4 MiB/s leaves room for a slower machine. The job
    # allowance assumes a browser upload no faster than 512 KiB/s, and stays
    # under Cloud Run's 60-minute request limit.
    parser_timeout: int = 30
    job_timeout: int = 240
    parse_bytes_per_second: int = 4 * 1024 * 1024
    transfer_bytes_per_second: int = 512 * 1024
    job_timeout_ceiling: int = 3300
    # The analysis worker's address-space cap on Linux, plus this multiple of
    # the file. Measured: about 1.2 x the file plus 40 MiB (issue #36).
    worker_memory_bytes: int = 768 * 1024 * 1024
    worker_memory_scale: int = 2
    temp_dir: str | None = None
    base_url: str = "http://localhost:8080"
    client_id: str = ""
    client_secret: str = ""
    session_key: str = ""
    # Google Picker's own developer key, distinct from the OAuth client
    # secret: it identifies the project to Google's picker UI and is
    # restricted by HTTP referrer in Cloud Console, not a value that needs
    # to stay off the client -- unlike client_secret, which never leaves
    # this process. "Add from Drive" is hidden in the UI while this is unset.
    picker_api_key: str = ""
    # The native Publisher reader (native/pub-parser). The app image builds it
    # in; elsewhere, point PUBLISHER_PARSER_BIN at a local build.
    publisher_parser: str = "/usr/local/bin/publisher-parser"
    # Converting a Publisher file hands its pictures to Slides through a
    # private Cloud Storage bucket and short-lived signed links
    # (docs/publisher-storage.md). Unset, a .pub can be checked but not
    # converted. The signer is the service account that signs the links; on
    # Cloud Run it defaults to the one the service runs as.
    publisher_bucket: str = ""
    publisher_signer: str = ""
    # After a Word conversion, fix the empty separator paragraphs that Google's
    # import turned into blank pages, by editing the new Google Doc (#54).
    # Off unless WMT_DOCX_REPAIR_BLANK_PAGES is set: it changes the person's
    # document after it is made, and documents.batchUpdate under drive.file
    # is not verified live.
    docx_repair_blank_pages: bool = False

    def entry_limit(self, source_bytes: int) -> int:
        return max(self.max_entry_bytes, self.entry_scale * source_bytes)

    def expanded_limit(self, source_bytes: int) -> int:
        return max(self.max_expanded_bytes, self.expanded_scale * source_bytes)

    def parser_timeout_for(self, source_bytes: int) -> int:
        return self.parser_timeout + source_bytes // self.parse_bytes_per_second

    def job_timeout_for(self, source_bytes: int) -> int:
        extra = source_bytes // self.transfer_bytes_per_second
        return min(self.job_timeout_ceiling, self.job_timeout + extra)

    def worker_memory_for(self, source_bytes: int) -> int:
        return self.worker_memory_bytes + self.worker_memory_scale * source_bytes

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def oauth_ready(self) -> bool:
        return bool(self.client_id and self.client_secret and self.session_key)

    @property
    def publisher_ready(self) -> bool:
        return bool(self.publisher_bucket)

    @property
    def picker_ready(self) -> bool:
        return bool(self.picker_api_key and self.oauth_ready)

    @property
    def picker_app_id(self) -> str:
        """The Cloud project number Picker needs via setAppId().

        Verified live (2026-09-28): a drive.file-scoped app's per-file grant
        on a picked file does not reliably take effect without this. It is
        the numeric prefix of the OAuth client ID itself -- Google always
        constructs a client ID as "<project number>-<random>.apps..." -- so
        no separate configuration value is needed.
        """
        return self.client_id.split("-", 1)[0]

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
        # Optional: unset (or empty) means no upload limit.
        raw = os.getenv("MAX_UPLOAD_SIZE", "").strip()
        limit = int(raw) if raw else None
        if limit is not None and limit <= 0:
            raise ValueError("MAX_UPLOAD_SIZE must be a positive number of bytes, or unset")
        return cls(
            max_upload_bytes=limit,
            base_url=base,
            temp_dir=os.getenv("TEMP_DIR"),
            client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            session_key=os.getenv("SESSION_ENCRYPTION_KEY", ""),
            picker_api_key=os.getenv("GOOGLE_PICKER_API_KEY", ""),
            publisher_parser=os.getenv("PUBLISHER_PARSER_BIN", "/usr/local/bin/publisher-parser"),
            publisher_bucket=os.getenv("PUBLISHER_BUCKET", "").strip(),
            publisher_signer=os.getenv("PUBLISHER_SIGNER", "").strip(),
            docx_repair_blank_pages=os.getenv("WMT_DOCX_REPAIR_BLANK_PAGES", "").strip().lower()
            in {"1", "true", "yes", "on"},
        )
