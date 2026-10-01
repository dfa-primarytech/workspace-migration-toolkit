"""Reads the VBA source out of an Office macro project (vbaProject.bin).

Two published formats, read with hard limits because the file is untrusted:

* [MS-CFB], the compound file that holds the project's streams;
* [MS-OVBA], the project's `dir` stream (which modules exist and where each
  one's source starts) and the compression its streams use.

Nothing here runs or interprets the code. The source is handed to the caller
to save beside the conversion and to translate (apps_script.py); it never
reaches a log or a report (DECISIONS.md, 2026-10-01).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
FREE, END = 0xFFFFFFFF, 0xFFFFFFFE
MAX_STREAM = 8 * 1024 * 1024  # a module's source, decompressed
MAX_MODULES = 500
MAX_SECTORS = 1 << 20

# [MS-OVBA] 2.3.4.2.3.2: MODULETYPE records
PROCEDURAL, DOCUMENT_OR_CLASS = 0x0021, 0x0022


class VbaUnreadable(Exception):
    """The project isn't one this reader can follow; its source is not used."""


@dataclass
class Module:
    name: str
    kind: str  # "standard", or "document" for a workbook, sheet or class module
    source: str


class Compound:
    """Just enough of [MS-CFB] to read named streams."""

    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != SIGNATURE:
            raise VbaUnreadable("not a compound file")
        self.data = data
        shift, mini_shift = struct.unpack_from("<HH", data, 30)
        if shift not in (9, 12) or mini_shift != 6:
            raise VbaUnreadable("unexpected sector size")
        self.sector, self.mini = 1 << shift, 1 << mini_shift
        fat_count, dir_start = (
            struct.unpack_from("<I", data, 44)[0],
            struct.unpack_from("<I", data, 48)[0],
        )
        self.cutoff = struct.unpack_from("<I", data, 56)[0]
        minifat_start, minifat_count, difat_start, difat_count = struct.unpack_from(
            "<IIII", data, 60
        )
        difat = list(struct.unpack_from("<109I", data, 76))
        seen: set[int] = set()
        sector = difat_start
        for _ in range(min(difat_count, MAX_SECTORS)):
            if sector in (FREE, END) or sector in seen:
                break
            seen.add(sector)
            entries = struct.unpack(f"<{self.sector // 4}I", self._sector(sector))
            difat += entries[:-1]
            sector = entries[-1]
        if fat_count > MAX_SECTORS:
            raise VbaUnreadable("too many FAT sectors")
        self.fat: list[int] = []
        for sector in difat[:fat_count]:
            self.fat += struct.unpack(f"<{self.sector // 4}I", self._sector(sector))
        directory = self._chain(dir_start)
        self.entries = [
            self._entry(directory[i : i + 128]) for i in range(0, len(directory) - 127, 128)
        ]
        if not self.entries:
            raise VbaUnreadable("no directory")
        root = self.entries[0]
        self.ministream = self._chain(root["start"])[: root["size"]]
        raw = self._chain(minifat_start) if minifat_count else b""
        self.minifat = list(struct.unpack(f"<{len(raw) // 4}I", raw[: len(raw) // 4 * 4]))

    def _sector(self, n: int) -> bytes:
        start = (n + 1) * self.sector
        if n >= MAX_SECTORS or start + self.sector > len(self.data):
            raise VbaUnreadable("sector out of range")
        return self.data[start : start + self.sector]

    def _chain(self, start: int) -> bytes:
        out: list[bytes] = []
        sector, seen = start, set()
        while sector not in (FREE, END):
            if sector in seen or sector >= len(self.fat) or len(out) > MAX_SECTORS:
                raise VbaUnreadable("broken sector chain")
            seen.add(sector)
            out.append(self._sector(sector))
            sector = self.fat[sector]
        return b"".join(out)

    @staticmethod
    def _entry(raw: bytes) -> dict:
        length = min(struct.unpack_from("<H", raw, 64)[0], 64)
        left, right, child = struct.unpack_from("<III", raw, 68)
        start, size = struct.unpack_from("<IQ", raw, 116)
        return {
            "name": raw[: max(length - 2, 0)].decode("utf-16-le", "replace"),
            "left": left,
            "right": right,
            "child": child,
            "start": start,
            "size": size,
        }

    def _children(self, index: int) -> list[int]:
        found, stack, seen = [], [self.entries[index]["child"]], set()
        while stack:
            i = stack.pop()
            if i == FREE or i >= len(self.entries) or i in seen:
                continue
            seen.add(i)
            found.append(i)
            stack += [self.entries[i]["left"], self.entries[i]["right"]]
        return found

    def stream(self, *path: str) -> bytes:
        index = 0
        for part in path:
            matches = [
                i
                for i in self._children(index)
                if self.entries[i]["name"].casefold() == part.casefold()
            ]
            if not matches:
                raise VbaUnreadable(f"no stream {part}")
            index = matches[0]
        entry = self.entries[index]
        if entry["size"] > MAX_STREAM:
            raise VbaUnreadable("stream too large")
        if entry["size"] >= self.cutoff:
            return self._chain(entry["start"])[: entry["size"]]
        out: list[bytes] = []
        sector, seen = entry["start"], set()
        while sector not in (FREE, END) and len(out) * self.mini < entry["size"]:
            if sector in seen or sector >= len(self.minifat):
                raise VbaUnreadable("broken mini chain")
            seen.add(sector)
            out.append(self.ministream[sector * self.mini : (sector + 1) * self.mini])
            sector = self.minifat[sector]
        return b"".join(out)[: entry["size"]]


def decompress(data: bytes) -> bytes:
    """[MS-OVBA] 2.4.1: a CompressedContainer, decompressed."""
    if not data or data[0] != 1:
        raise VbaUnreadable("not a compressed container")
    out, pos = bytearray(), 1
    while pos + 2 <= len(data):
        header = struct.unpack_from("<H", data, pos)[0]
        end = min(pos + (header & 0x0FFF) + 3, len(data))
        pos += 2
        if not header & 0x8000:  # a raw chunk: 4096 bytes as they are
            out += data[pos : pos + 4096]
            pos += 4096
        else:
            chunk = bytearray()
            while pos < end:
                flags = data[pos]
                pos += 1
                for bit in range(8):
                    if pos >= end:
                        break
                    if not flags & (1 << bit):
                        chunk.append(data[pos])
                        pos += 1
                        continue
                    if pos + 2 > end or not chunk:
                        raise VbaUnreadable("bad copy token")
                    token = struct.unpack_from("<H", data, pos)[0]
                    pos += 2
                    bits = max((len(chunk) - 1).bit_length(), 4)
                    offset = (token >> (16 - bits)) + 1
                    length = (token & (0xFFFF >> bits)) + 3
                    if offset > len(chunk):
                        raise VbaUnreadable("copy token reaches before the chunk")
                    for _ in range(length):
                        chunk.append(chunk[-offset])
            out += chunk
        if len(out) > MAX_STREAM:
            raise VbaUnreadable("decompressed too large")
    return bytes(out)


def _directory(dir_stream: bytes) -> list[tuple[str, str, int, str]]:
    """(module name, stream name, source offset, kind), from the dir stream."""
    modules, pos = [], 0
    name = stream = None
    offset, kind = None, "standard"
    while pos + 6 <= len(dir_stream):
        record, size = struct.unpack_from("<HI", dir_stream, pos)
        if record == 0x0009:  # PROJECTVERSION: its size says 4, but 6 bytes follow
            size = 6
        body = dir_stream[pos + 6 : pos + 6 + size]
        pos += 6 + size
        if record == 0x0019:  # MODULENAME starts a module
            name, stream, offset, kind = body.decode("cp1252", "replace"), None, None, "standard"
        elif record == 0x001A:
            stream = body.decode("cp1252", "replace")
        elif record == 0x0031 and len(body) == 4:
            offset = struct.unpack("<I", body)[0]
        elif record == PROCEDURAL:
            kind = "standard"
        elif record == DOCUMENT_OR_CLASS:
            kind = "document"
        elif record == 0x002B and name and stream and offset is not None:  # module terminator
            modules.append((name, stream, offset, kind))
            if len(modules) > MAX_MODULES:
                raise VbaUnreadable("too many modules")
            name = None
    return modules


def read_modules(project: bytes) -> list[Module]:
    """Every module's source, in the project's order."""
    try:
        compound = Compound(project)
        found = []
        for name, stream, offset, kind in _directory(decompress(compound.stream("VBA", "dir"))):
            raw = compound.stream("VBA", stream)
            if offset > len(raw):
                raise VbaUnreadable("source offset past its stream")
            source = decompress(raw[offset:]).decode("cp1252", "replace")
            found.append(Module(name, kind, source.replace("\r\n", "\n")))
        return found
    except (struct.error, IndexError, ValueError) as error:
        raise VbaUnreadable(type(error).__name__) from error
