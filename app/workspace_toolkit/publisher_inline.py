"""Pictures set inline in text, which libmspub leaves out.

A Publisher picture can sit in a line of text instead of on the page: PUB-002's
book covers are each on their own line in a table cell, under the book's
title. libmspub draws only shapes that belong to a page, and an inline picture
belongs to the text instead (a Contents record that is not a page), so it
never reaches the reader. The text keeps its place as U+FFFC, the object
replacement character, and the picture stays in the drawing records.

Those records say, for each picture shape, which stored picture it shows, its
size, and its Contents sequence number. The stored pictures themselves are in
a second stream (`drawing-pictures.bin`, Escher/EscherDelayStm). Every picture
libmspub did place was extracted, so a picture shape whose stored picture
matches none of the reader's assets is one it left out.

A picture is only placed when it is certain: there must be exactly as many of
those shapes as U+FFFC marks in the text. They are then paired in order, the
shapes by sequence number and the marks in reading order (PUB-002: 7 and 7).
Anything else leaves the marks empty and says so.

Nothing here decodes an image. It walks records by their own lengths, within
the buffers, and hands the stored bytes on to be checked like any picture.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .publisher_art import Picture, _open, usable
from .publisher_crop import BSTORE, DG, DGG, FBSE, FOPT, FSP, SP, SPGR, _asset_for, _records

MARK = "￼"
ANCHOR, CLIENT = 0xF010, 0xF011
PIB, FILL_BLIP = 0x0104, 0x0186
PICTURE_SHAPES = {1, 75}  # a rectangle filled with a picture, a picture frame
EMU_PER_POINT = 12700
# Stored picture record types, with the instances that carry a second UID.
BLIPS = {
    0xF01D: ("image/jpeg", {0x46B, 0x6E3}),
    0xF01E: ("image/png", {0x6E1}),
}


@dataclass(frozen=True)
class Inline:
    """A picture set in text: what it shows, and how large it is."""

    seq: int  # its Contents sequence number: the order it comes in the text
    blip: int  # 1-based, into the picture store
    width: float  # points
    height: float


@dataclass(frozen=True)
class Stored:
    size: int  # the stored record's size, as the reader's assets are matched
    offset: int  # into drawing-pictures.bin


def _blocks(buf: bytes, start: int, end: int) -> dict[int, int]:
    """Publisher's own numbered values in a client record: a length, then
    (id, type, value) with 4-byte values (type 0x20 or 0x68)."""
    values: dict[int, int] = {}
    if start + 4 > end:
        return values
    length = struct.unpack_from("<I", buf, start)[0]
    pos, stop = start + 4, min(end, start + length)
    while pos + 6 <= stop:
        ident, kind = buf[pos], buf[pos + 1]
        if kind not in (0x20, 0x68):
            break  # a value this reader does not know the size of
        values[ident] = struct.unpack_from("<I", buf, pos + 2)[0]
        pos += 6
    return values


def read(buf: bytes) -> tuple[list[Stored], list[Inline]]:
    """The picture store, and every picture shape with a size and a sequence number."""
    stored: list[Stored] = []
    shapes: list[Inline] = []

    def walk(start: int, end: int) -> None:
        for _, kind, body, length in _records(buf, start, end):
            if kind == SPGR:
                walk(body, body + length)
            elif kind == SP:
                shape_type = -1
                props: dict[int, int] = {}
                anchor: dict[int, int] = {}
                client: dict[int, int] = {}
                for inner_count, inner, ibody, ilength in _records(buf, body, body + length):
                    if inner == FSP:
                        shape_type = inner_count
                    elif inner == FOPT and inner_count * 6 <= ilength:
                        for i in range(inner_count):
                            key, value = struct.unpack_from("<HI", buf, ibody + i * 6)
                            props[key & 0x3FFF] = value
                    elif inner == ANCHOR:
                        anchor = _blocks(buf, ibody, ibody + ilength)
                    elif inner == CLIENT:
                        client = _blocks(buf, ibody, ibody + ilength)
                blip = props.get(PIB) or props.get(FILL_BLIP)
                seq = client.get(1)
                if shape_type in PICTURE_SHAPES and blip and seq is not None and anchor:
                    left, top = _signed(anchor.get(1, 0)), _signed(anchor.get(2, 0))
                    right, bottom = _signed(anchor.get(3, 0)), _signed(anchor.get(4, 0))
                    if right > left and bottom > top:
                        shapes.append(
                            Inline(
                                seq,
                                blip,
                                (right - left) / EMU_PER_POINT,
                                (bottom - top) / EMU_PER_POINT,
                            )
                        )

    for _, kind, body, length in _records(buf, 0, len(buf)):
        if kind == DGG:
            for _, inner, ibody, ilength in _records(buf, body, body + length):
                if inner == BSTORE:
                    for _, entry, ebody, elength in _records(buf, ibody, ibody + ilength):
                        if entry == FBSE and elength >= 36:
                            size, _, delay = struct.unpack_from("<III", buf, ebody + 20)
                            stored.append(Stored(size, delay))
        elif kind == DG:
            for _, inner, ibody, ilength in _records(buf, body, body + length):
                if inner == SPGR:
                    walk(ibody, ibody + ilength)
    return stored, shapes


def _signed(value: int) -> int:
    return value - (1 << 32) if value >= 1 << 31 else value


def picture_bytes(pictures: bytes, offset: int) -> tuple[bytes, str] | None:
    """A stored JPEG or PNG, as its own file's bytes, or None."""
    if offset + 8 > len(pictures):
        return None
    head, kind, length = struct.unpack_from("<HHI", pictures, offset)
    known = BLIPS.get(kind)
    if known is None or offset + 8 + length > len(pictures):
        return None
    mime, two = known
    skip = 16 * (2 if head >> 4 in two else 1) + 1  # the UID(s), then a tag byte
    if length <= skip:
        return None
    start = offset + 8 + skip
    return pictures[start : offset + 8 + length], mime


def marks(document: dict) -> Iterator[tuple[str, int, int, int]]:
    """Where each U+FFFC is, in reading order: (element id, row, column,
    paragraph index), row and column -1 outside a table."""
    for page in document.get("pages", []):
        for element in page.get("elements", []):
            table = element.get("table")
            if table:
                for row in table.get("rows", []):
                    for cell in row.get("cells", []):
                        for index, paragraph in enumerate(cell.get("paragraphs", [])):
                            for _ in range(_count(paragraph)):
                                yield element["id"], cell["row"], cell["column"], index
            # A text box keeps its paragraphs on the element itself.
            for index, paragraph in enumerate(element.get("paragraphs") or []):
                for _ in range(_count(paragraph)):
                    yield element["id"], -1, -1, index


def _count(paragraph: dict) -> int:
    total = 0
    for run in paragraph.get("runs", []):
        items = run.get("items")
        if items:
            total += sum(i.get("value", "").count(MARK) for i in items if i.get("kind") == "text")
        else:
            total += run.get("text", "").count(MARK)
    return total


def recovered(
    bundle: Path, document: dict, assets: dict, out: Path
) -> tuple[dict[tuple[str, int, int, int], list[tuple[Path, str, Inline]]], list[dict]]:
    """Each inline picture, written out for checking, by the mark it replaces."""
    where = list(marks(document))
    drawing, pictures = bundle / "drawing.bin", bundle / "drawing-pictures.bin"
    if not where:
        return {}, []
    if not drawing.is_file() or not pictures.is_file():
        return {}, [_unplaced(len(where))]
    stored, shapes = read(drawing.read_bytes())
    known = assets.get("assets", [])
    left_out = sorted(
        (
            s
            for s in shapes
            if 0 < s.blip <= len(stored) and not _asset_for(stored[s.blip - 1].size, known)
        ),
        key=lambda s: s.seq,
    )
    if len(left_out) != len(where):
        return {}, [_unplaced(len(where))]
    data = pictures.read_bytes()
    out.mkdir(parents=True, exist_ok=True)
    found: dict[tuple[str, int, int, int], list[tuple[Path, str, Inline]]] = {}
    for number, (mark, shape) in enumerate(zip(where, left_out, strict=True)):
        got = picture_bytes(data, stored[shape.blip - 1].offset)
        if got is None:
            return {}, [_unplaced(len(where))]
        payload, mime = got
        path = out / f"inline_{number:03d}.{'png' if mime == 'image/png' else 'jpg'}"
        path.write_bytes(payload)
        found.setdefault(mark, []).append((path, mime, shape))
    return found, []


def prepared(
    bundle: Path, document: dict, assets: dict, out: Path
) -> tuple[dict[tuple[str, int, int, int], list[tuple[Picture, Inline]]], list[dict]]:
    """The inline pictures as Slides will take them, checked like any picture."""
    found, notes = recovered(bundle, document, assets, out)
    ready: dict[tuple[str, int, int, int], list[tuple[Picture, Inline]]] = {}
    refused = 0
    for mark, items in found.items():
        for path, mime, shape in items:
            image = _open(path)
            if image is None:
                refused += 1
                continue
            asset = {
                "id": path.stem,
                "filename": str(path),
                "mimeType": mime,
                "pixelWidth": image.width,
                "pixelHeight": image.height,
                "byteLength": path.stat().st_size,
            }
            picture, _ = usable(asset, bundle, out)
            if picture is None:
                refused += 1
                continue
            ready.setdefault(mark, []).append((picture, shape))
    if refused:
        notes.append(_unplaced(refused))
    return ready, notes


def _unplaced(count: int) -> dict:
    return {
        "code": "inline-pictures-unplaced",
        "message": f"{count} picture(s) set in the text could not be recovered, so they are "
        "missing: add them in Slides.",
    }
