"""WordArt, recovered from Publisher's drawing records.

libmspub draws a WordArt shape as its outline only: for "plain text" WordArt
(Office shape type 136) that is two horizontal lines, the top and bottom of
the text's path, and it never reads the text. PUB-001's title, "Early
Reading at St.Vincent's", came out as two purple lines and no words.

The text, font, size, weight and colours are Office drawing properties on
the shape (gtextUNICODE 0xC0, gtextFont 0xC5, gtextSize 0xC3, the gtext
flags 0xFF, fillColor 0x181, lineColor 0x1C0), in the same records the crops
come from (`drawing.bin`). This reads them, then matches each WordArt to the
outline libmspub drew for it: a layer of paths in the WordArt's own line
colour, in drawing order. The renderer puts an editable text box there
instead of the lines. Effects (gradient fill, outline, shadow or reflection,
the text's warp) are not recreated, and the report says so.
"""

from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .publisher_art import subpaths
from .publisher_crop import DG, FOPT, FSP, SP, SPGR, _records

WORDART = range(136, 176)  # Office's text-effect shape types
TEXT, SIZE, FONT, FLAGS = 0x00C0, 0x00C3, 0x00C5, 0x00FF
FILL_COLOUR, LINE_COLOUR = 0x0181, 0x01C0
BOLD, ITALIC = 0x20, 0x10
MAX_TEXT = 64 * 1024


@dataclass(frozen=True)
class WordArt:
    text: str
    font: str | None
    size: float | None
    bold: bool
    italic: bool
    colour: str | None  # "#rrggbb"
    line: str | None


def _colour(value: int | None) -> str | None:
    """An Office colour: red, green and blue in the low three bytes. A scheme or
    system colour (a flag in the high byte) can't be resolved here."""
    if value is None or value >> 24:
        return None
    return f"#{value & 0xFF:02x}{(value >> 8) & 0xFF:02x}{(value >> 16) & 0xFF:02x}"


def _utf16(blob: bytes) -> str:
    return blob.decode("utf-16-le", "replace").split("\0", 1)[0]


def read(buf: bytes) -> list[WordArt]:
    """Every WordArt shape in the records, in drawing order."""
    found: list[WordArt] = []

    def walk(start: int, end: int) -> None:
        for _, kind, body, length in _records(buf, start, end):
            if kind == SPGR:
                walk(body, body + length)
            elif kind == SP:
                shape_type = None
                fixed: dict[int, int] = {}
                blobs: dict[int, bytes] = {}
                for count, inner, ibody, ilength in _records(buf, body, body + length):
                    if inner == FSP:
                        shape_type = count  # the record's instance is the shape type
                    elif inner == FOPT and count * 6 <= ilength:
                        data = ibody + count * 6
                        for i in range(count):
                            pid, value = struct.unpack_from("<HI", buf, ibody + i * 6)
                            key = pid & 0x3FFF
                            if pid & 0x8000:  # complex: its data follows the table
                                if value > MAX_TEXT or data + value > ibody + ilength:
                                    break
                                blobs[key] = buf[data : data + value]
                                data += value
                            else:
                                fixed[key] = value
                if shape_type in WORDART and TEXT in blobs:
                    text = _utf16(blobs[TEXT]).replace("\r\n", "\n").replace("\r", "\n")
                    lines = [line.strip() for line in text.split("\n")]
                    flags = fixed.get(FLAGS, 0)
                    found.append(
                        WordArt(
                            text="\n".join(line for line in lines if line),
                            font=_utf16(blobs[FONT]) if FONT in blobs else None,
                            size=fixed[SIZE] / 65536 if SIZE in fixed else None,
                            bold=bool(flags & BOLD and flags >> 16 & BOLD),
                            italic=bool(flags & ITALIC and flags >> 16 & ITALIC),
                            colour=_colour(fixed.get(FILL_COLOUR)),
                            line=_colour(fixed.get(LINE_COLOUR)),
                        )
                    )

    for _, kind, body, length in _records(buf, 0, len(buf)):
        if kind == DG:
            for _, inner, ibody, ilength in _records(buf, body, body + length):
                if inner == SPGR:
                    walk(ibody, ibody + ilength)
    return [w for w in found if w.text]


def outlines(document: dict) -> list[tuple[str, tuple[float, float, float, float], str | None]]:
    """Where libmspub drew a WordArt's outline: a layer holding only paths.

    Returns (layer id, box on the page, stroke colour) in drawing order.
    """
    out = []
    for page in document.get("pages", []):
        if page.get("kind", "page") != "page":
            continue
        children: dict[str, list[dict]] = defaultdict(list)
        for element in page.get("elements", []):
            if element.get("parentId"):
                children[element["parentId"]].append(element)
        for element in sorted(page.get("elements", []), key=lambda e: e["zIndex"]):
            kids = children.get(element["id"], [])
            if element.get("type") != "wrapper" or not kids:
                continue
            if any(k.get("type") != "path" for k in kids):
                continue
            points = [
                point
                for kid in kids
                for piece in subpaths((kid.get("geometry") or {}).get("path", []))
                for point in piece.points
            ]
            if not points:
                continue
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            stroke = next(
                (
                    k["source"]["styleProperties"].get("svg:stroke-color")
                    for k in kids
                    if k["source"]["styleProperties"].get("draw:stroke") not in (None, "none")
                ),
                None,
            )
            box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            out.append((element["id"], box, stroke))
    return out


def placed(bundle: Path, document: dict) -> tuple[dict[str, tuple[WordArt, tuple]], list[dict]]:
    """Each WordArt, by the id of the layer libmspub drew its outline in, with its box.

    Matched in drawing order among outlines of the WordArt's own line colour.
    A WordArt left unmatched is reported with its text, so it is not lost.
    """
    path = bundle / "drawing.bin"
    if not path.is_file():
        return {}, []
    try:
        arts = read(path.read_bytes())
    except (struct.error, ValueError):
        return {}, []
    free = outlines(document)
    result: dict[str, tuple[WordArt, tuple]] = {}
    notes: list[dict] = []
    for art in arts:
        match = next(
            (o for o in free if o[2] and art.line and o[2].lower() == art.line.lower()), None
        )
        if match is None or match[1][2] <= 0 or match[1][3] <= 0:
            notes.append(
                {
                    "code": "wordart-unplaced",
                    "message": f'WordArt reading "{art.text}" could not be placed on its '
                    "page: add it by hand.",
                }
            )
            continue
        free.remove(match)
        result[match[0]] = (art, match[1])
    return result, notes
