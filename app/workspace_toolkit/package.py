from __future__ import annotations

import hashlib
import io
import posixpath
import re
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
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_MAIN_MIME = XLSX_MIME + ".main+xml"
XLSM_MIME = "application/vnd.ms-excel.sheet.macroEnabled.12"
XLSM_MAIN_MIME = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
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
    aliases: tuple[str, ...] = ()  # other MIME types browsers send for it
    allow_macros: bool = False


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

XLSX = Format(
    key="xlsx",
    suffix=".xlsx",
    mime=XLSX_MIME,
    main_part="xl/workbook.xml",
    main_mime=XLSX_MAIN_MIME,
    noun="workbook",
    chooser="an Excel .xlsx file",
)

XLSM = Format(
    key="xlsm",
    suffix=".xlsm",
    mime=XLSM_MIME,
    main_part="xl/workbook.xml",
    main_mime=XLSM_MAIN_MIME,
    noun="macro-enabled workbook",
    chooser="an Excel .xlsm file",
    allow_macros=True,
)

# Not an OOXML package at all: an OLE compound file read by publisher-parser.
# The zip-specific fields are empty; nothing opens a .pub as a Package.
PUB = Format(
    key="pub",
    suffix=".pub",
    mime="application/x-mspublisher",
    main_part="",
    main_mime="",
    noun="publication",
    chooser="a Publisher .pub file",
    aliases=("application/vnd.ms-publisher",),
)

FORMATS = {fmt.suffix: fmt for fmt in (PPTX, DOCX, XLSX, XLSM)}


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
    accepted_mimes = {fmt.mime.lower(), *(alias.lower() for alias in fmt.aliases)}
    if mime.split(";", 1)[0].lower() not in {*accepted_mimes, "application/octet-stream"}:
        raise ToolkitError("invalid_mime", f"This file does not have a supported {fmt.key} type.")


class Package:
    def __init__(self, path: Path, settings: Settings, fmt: Format = PPTX):
        self.settings = settings
        self.format = fmt
        size = path.stat().st_size
        if settings.max_upload_bytes is not None and size > settings.max_upload_bytes:
            raise ToolkitError("upload_too_large", "This file exceeds the upload size limit.", 413)
        # In proportion to this file, never below the configured floors.
        self.entry_limit = settings.entry_limit(size)
        self.expanded_limit = settings.expanded_limit(size)
        with path.open("rb") as stream:
            signature = stream.read(8)
            if signature == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                raise ToolkitError("encrypted_package", "Encrypted Office files cannot be read.")
            if signature[:4] != b"PK\x03\x04":
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
                info.file_size > self.entry_limit
                or total > self.expanded_limit
                or info.file_size > max(info.compress_size, 1) * self.settings.max_compression_ratio
            ):
                raise ToolkitError("zip_limits", "The expanded file exceeds processing limits.")
            self.names.add(name)
        self._by_casefold = {name.casefold(): name for name in self.names}
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
        has_macros = any("vbaproject" in n.lower() for n in self.names) or any(
            "macroenabled" in t.lower() or "vbaproject" in t.lower()
            for t in [*self.defaults.values(), *self.overrides.values()]
        )
        if has_macros and not fmt.allow_macros:
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
        bound = limit or self.entry_limit
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
        data = self.read(name, self.settings.max_xml_bytes)
        limit = self.settings.max_xml_elements
        root: Element | None = None
        try:
            # Counted as the parser goes, so an over-limit part is refused
            # before its whole tree is in memory rather than after.
            events = SafeET.iterparse(io.BytesIO(data), events=("start",), forbid_dtd=True)
            for count, (_, element) in enumerate(events, start=1):
                if root is None:
                    root = element
                if count > limit:
                    raise ToolkitError(
                        "xml_limit",
                        f"A part of this file has more than {limit:,} elements, the most "
                        "the converter processes. Very long documents can reach this.",
                    )
        except (SafeET.ParseError, DefusedXmlException) as exc:
            raise ToolkitError(
                "invalid_xml", "The file contains unsafe or damaged markup."
            ) from exc
        if root is None:  # an empty part is a parse error, so this is defensive
            raise ToolkitError("invalid_xml", "The file contains unsafe or damaged markup.")
        return root

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
            missing = False
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
                if resolved.startswith("../") or resolved == "..":
                    raise ToolkitError(
                        "unsafe_relationship", "The file contains an unsafe component link."
                    )
                # OPC part names are case-insensitive, so Word and PowerPoint
                # follow "Styles.xml" to word/styles.xml; so do we.
                resolved = self._by_casefold.get(resolved.casefold())
                # A link to a part that is not there is a defect, not a threat:
                # some generators write Target="../NULL" for a removed picture,
                # and Office opens those files. Record it for the caller to
                # report rather than refusing the whole file (issue #47).
                missing = resolved is None
            result.append(
                {
                    "id": rid,
                    "type": rel.get("Type", ""),
                    "target": target,
                    "external": external,
                    "resolved": resolved,
                    "missing": missing,
                }
            )
        return result

    def close(self) -> None:
        self.zip.close()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ editing parts
#
# Package parts are edited as bytes, so the rest of each part stays exactly as
# written, and every edit is then read back with the XML parser. A tag may carry
# any prefix, and may be empty (<x/>) or paired (<x></x>): both are valid
# (#136, #137). An edit that can't be confirmed returns None and is not made.

_PREFIX = rb"(?:[A-Za-z_][\w.-]*:)?"
_ATTRIBUTE = rb"\s{}\s*=\s*([\"'])(.*?)\1"


def tags(name: bytes) -> re.Pattern[bytes]:
    """Every <name> element, with or without a prefix, empty or paired."""
    return re.compile(
        rb"<(?P<q>" + _PREFIX + name + rb")\b(?P<attrs>[^>]*?)(?:/>|>.*?</(?P=q)\s*>)", re.S
    )


def attribute(tag: bytes, name: str) -> str | None:
    found = re.search(_ATTRIBUTE.replace(b"{}", re.escape(name.encode())), tag)
    return found.group(2).decode("utf-8", "replace") if found else None


RELATIONSHIPS = tags(b"Relationship")
OVERRIDES = tags(b"Override")


def _parsed(data: bytes) -> Element | None:
    try:
        return SafeET.fromstring(data)
    except (SafeET.ParseError, DefusedXmlException):
        return None


def without_relationships(data: bytes, ids: set[str]) -> bytes | None:
    """A .rels part without these relationships, checked."""
    result = RELATIONSHIPS.sub(
        lambda m: b"" if attribute(m["attrs"], "Id") in ids else m.group(0), data
    )
    root = _parsed(result)
    if root is None or any(rel.get("Id") in ids for rel in root):
        return None
    return result


def without_overrides(types: bytes, parts: set[str]) -> bytes | None:
    """[Content_Types].xml without the overrides for these parts, checked.
    `parts` are part names as in the zip (no leading slash)."""
    gone = {"/" + part.casefold() for part in parts}
    result = OVERRIDES.sub(
        lambda m: (
            b"" if (attribute(m["attrs"], "PartName") or "").casefold() in gone else m.group(0)
        ),
        types,
    )
    root = _parsed(result)
    if root is None or any(
        (node.get("PartName") or "").casefold() in gone
        for node in root.iter(f"{{{CONTENT_NS}}}Override")
    ):
        return None
    return result


def with_default(types: bytes, extension: str, content_type: str) -> bytes | None:
    """[Content_Types].xml declaring a content type for an extension, checked.
    The new Default takes the root's own prefix, so a prefixed document stays
    in the content-types namespace."""
    root = _parsed(types)
    if root is None or root.tag != f"{{{CONTENT_NS}}}Types":
        return None
    for node in root.iter(f"{{{CONTENT_NS}}}Default"):
        if (node.get("Extension") or "").casefold() == extension.casefold():
            return types
    closing = list(re.finditer(rb"</(" + _PREFIX + rb")Types\s*>", types))
    if not closing:
        return None  # an empty <Types/> never holds a picture's part
    end = closing[-1]
    prefix = end.group(1)
    added = b'<%sDefault Extension="%s" ContentType="%s"/>' % (
        prefix,
        extension.encode(),
        content_type.encode(),
    )
    result = types[: end.start()] + added + types[end.start() :]
    checked = _parsed(result)
    if checked is None or not any(
        (node.get("Extension") or "").casefold() == extension.casefold()
        and node.get("ContentType") == content_type
        for node in checked.iter(f"{{{CONTENT_NS}}}Default")
    ):
        return None
    return result
