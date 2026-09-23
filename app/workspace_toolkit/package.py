from __future__ import annotations

import hashlib
import posixpath
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

# Type annotation only; XML parsing always uses defusedxml.
from xml.etree.ElementTree import Element  # nosec B405

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from .config import Settings
from .errors import ToolkitError

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MAIN_MIME = PPTX_MIME + ".main+xml"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_MAIN_MIME = DOCX_MIME + ".main+xml"
CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass(frozen=True)
class Format:
    """The handful of things that differ between one OOXML family and another.

    Every other guard in this module -- zip-bomb limits, path traversal,
    symlinks, encryption, duplicate names, macro detection -- is identical
    across formats, so it is written once and parameterised rather than copied.
    """

    key: str
    suffix: str
    mime: str
    main_part: str
    main_mime: str
    noun: str  # used in user-facing messages, e.g. "PowerPoint presentation"
    chooser: str  # e.g. "a PowerPoint .pptx file"


PPTX = Format(
    key="pptx",
    suffix=".pptx",
    mime=PPTX_MIME,
    main_part="ppt/presentation.xml",
    main_mime=MAIN_MIME,
    noun="presentation",
    chooser="a PowerPoint .pptx file",
)

DOCX = Format(
    key="docx",
    suffix=".docx",
    mime=DOCX_MIME,
    main_part="word/document.xml",
    main_mime=DOCX_MAIN_MIME,
    noun="document",
    chooser="a Word .docx file",
)

FORMATS = {fmt.suffix: fmt for fmt in (PPTX, DOCX)}


def validate_upload_name(filename: str, mime: str, fmt: Format = PPTX) -> None:
    if (
        not filename
        or len(filename) > 240
        or any(c in filename for c in "/\\")
        or any(ord(c) < 32 for c in filename)
    ):
        raise ToolkitError("invalid_filename", f"Please choose {fmt.chooser}.")
    if not filename.lower().endswith(fmt.suffix):
        raise ToolkitError("unsupported_type", f"Only {fmt.chooser} files are supported here.")
    if mime.split(";", 1)[0].lower() not in {fmt.mime, "application/octet-stream"}:
        raise ToolkitError("invalid_mime", f"This file does not have a supported {fmt.key} type.")


class Package:
    def __init__(self, path: Path, settings: Settings, fmt: Format = PPTX):
        self.settings = settings
        self.format = fmt
        if path.stat().st_size > settings.max_upload_bytes:
            raise ToolkitError("upload_too_large", "This file exceeds the upload size limit.", 413)
        with path.open("rb") as stream:
            if stream.read(4) != b"PK\x03\x04":
                raise ToolkitError("invalid_signature", f"This is not a valid {fmt.suffix} file.")
        try:
            self.zip = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise ToolkitError("invalid_package", f"The {fmt.key} file is damaged.") from exc
        try:
            self._validate()
        except BaseException:
            self.zip.close()
            raise

    def _validate(self) -> None:
        infos = self.zip.infolist()
        if len(infos) > self.settings.max_entries:
            raise ToolkitError("zip_entries", "This file contains too many package entries.")
        self.names: set[str] = set()
        seen: set[str] = set()
        total = 0
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                not name
                or name != info.orig_filename
                or "\\" in name
                or "\x00" in name
                or ":" in name
                or name.startswith("/")
                or ".." in parts
                or "." in name.split("/")
                or stat.S_ISLNK(mode)
                or name.casefold() in seen
            ):
                raise ToolkitError("unsafe_package", "The file contains unsafe package paths.")
            seen.add(name.casefold())
            if info.is_dir():
                continue
            if info.flag_bits & 1 or info.compress_type not in {
                zipfile.ZIP_STORED,
                zipfile.ZIP_DEFLATED,
            }:
                raise ToolkitError(
                    "encrypted_package", "Encrypted or unsupported archives cannot be read."
                )
            total += info.file_size
            if (
                info.file_size > self.settings.max_entry_bytes
                or total > self.settings.max_expanded_bytes
                or info.file_size > max(info.compress_size, 1) * self.settings.max_compression_ratio
            ):
                raise ToolkitError("zip_limits", "The expanded file exceeds processing limits.")
            self.names.add(name)
        fmt = self.format
        if "[Content_Types].xml" not in self.names or fmt.main_part not in self.names:
            raise ToolkitError("invalid_package", f"The file is not a valid {fmt.key} package.")
        ct = self.xml("[Content_Types].xml")
        if ct.tag != f"{{{CONTENT_NS}}}Types":
            raise ToolkitError("invalid_package", "The package content types are invalid.")
        self.defaults = {
            e.get("Extension", "").lower(): e.get("ContentType", "")
            for e in ct
            if e.tag.endswith("}Default")
        }
        self.overrides = {
            e.get("PartName", "").lstrip("/"): e.get("ContentType", "")
            for e in ct
            if e.tag.endswith("}Override")
        }
        if self.overrides.get(fmt.main_part) != fmt.main_mime:
            raise ToolkitError(
                "unsupported_type", f"Only macro-free {fmt.suffix} files are supported."
            )
        if any("vbaproject" in n.lower() for n in self.names) or any(
            "macroenabled" in t.lower() or "vbaproject" in t.lower()
            for t in [*self.defaults.values(), *self.overrides.values()]
        ):
            raise ToolkitError(
                "macros_rejected", f"A {fmt.noun} containing macros is not supported."
            )

    def mime(self, name: str) -> str:
        return self.overrides.get(
            name, self.defaults.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")
        )

    def read(self, name: str, limit: int | None = None) -> bytes:
        if name not in self.names:
            raise ToolkitError("missing_part", "The file is missing a required component.")
        bound = limit or self.settings.max_entry_bytes
        if self.zip.getinfo(name).file_size > bound:
            raise ToolkitError("part_limit", "A file component exceeds processing limits.")
        try:
            with self.zip.open(name) as stream:
                data = stream.read(bound + 1)
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise ToolkitError("damaged_part", "A file component is damaged.") from exc
        if len(data) > bound:
            raise ToolkitError("part_limit", "A file component exceeds processing limits.")
        return data

    def xml(self, name: str) -> Element:
        try:
            root = SafeET.fromstring(self.read(name, self.settings.max_xml_bytes), forbid_dtd=True)
            limit = self.settings.max_xml_elements
            if sum(1 for _ in root.iter()) > limit:
                # Say what the limit is and what it counts. "Too complex" sent
                # people looking at their pictures and their tables when the
                # cause was simply length, and the 25 MB upload limit made the
                # file look like it should have been fine.
                raise ToolkitError(
                    "xml_limit",
                    f"One part of this document has more than {limit:,} pieces of markup, "
                    "which is usually a very long document. Please split it and convert "
                    "each part.",
                )
            return root
        except (SafeET.ParseError, DefusedXmlException) as exc:
            raise ToolkitError(
                "invalid_xml", "The file contains unsafe or damaged markup."
            ) from exc

    def relationships(self, part: str) -> list[dict]:
        name = (
            posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            if part
            else "_rels/.rels"
        )
        if name not in self.names:
            return []
        root = self.xml(name)
        if root.tag != f"{{{REL_NS}}}Relationships":
            raise ToolkitError("invalid_relationships", "The file relationships are invalid.")
        result = []
        ids: set[str] = set()
        for rel in root:
            rid = rel.get("Id", "")
            if not rid or rid in ids:
                raise ToolkitError(
                    "invalid_relationships", "The file has duplicate relationship IDs."
                )
            ids.add(rid)
            target = rel.get("Target", "")
            external = rel.get("TargetMode") == "External"
            resolved = None
            if not external:
                decoded = unquote(target)
                if "\\" in decoded or "\x00" in decoded or urlsplit(decoded).scheme:
                    raise ToolkitError(
                        "unsafe_relationship", "The file contains an unsafe component link."
                    )
                decoded = decoded.split("#", 1)[0]
                resolved = posixpath.normpath(
                    decoded.lstrip("/")
                    if decoded.startswith("/")
                    else posixpath.join(posixpath.dirname(part), decoded)
                )
                if resolved.startswith("../") or resolved == ".." or resolved not in self.names:
                    raise ToolkitError(
                        "missing_relationship",
                        "The file contains a missing or unsafe component link.",
                    )
            result.append(
                {
                    "id": rid,
                    "type": rel.get("Type", ""),
                    "target": target,
                    "external": external,
                    "resolved": resolved,
                }
            )
        return result

    def close(self) -> None:
        self.zip.close()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
