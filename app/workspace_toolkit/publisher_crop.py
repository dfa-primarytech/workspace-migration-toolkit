"""Recovering each picture's crop from Publisher's own drawing records.

libmspub reads a picture's crop ("crop from top, bottom, left, right", Office
drawing properties 0x100 to 0x103) and drops it, so the reader would hand
over the whole picture and the renderer stretch it into its cropped frame.
PUB-001's banner is one picture shown on page 1 as a thin strip and on page 4
trimmed further on the right. The parser saves Publisher's drawing records
unchanged as `drawing.bin`; this reads the crops back from them.

A crop is only used when it is certain:

- each picture shape names a stored picture, which is matched to one of
  the reader's assets by its size;
- a picture used more than once is paired with its placements in order,
  or in whichever order makes every pairing fit;
- the cropped picture must have the frame's own shape (within 3%). That is
  what a crop is for, so a crop that fails it is not applied.

Anything else leaves the picture as it was and says why. Nothing here
decodes an image: it reads fixed-size numbers from a stream the reader has
already accepted, walking records by their own lengths, within the buffer.
"""

from __future__ import annotations

import itertools
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

DGG, BSTORE, DG, SPGR, SP = 0xF000, 0xF001, 0xF002, 0xF003, 0xF004
FSP, FOPT, FBSE = 0xF00A, 0xF00B, 0xF007
PIB, FILL_BLIP = 0x0104, 0x0186
CROP = (0x0100, 0x0101, 0x0102, 0x0103)  # top, bottom, left, right
SIZE_SLACK = 64  # bytes between a stored picture's record and the extracted payload
SHAPE_TOLERANCE = 0.03
MAX_PERMUTED = 6  # uses of one picture tried in every order; beyond, in order only


@dataclass(frozen=True)
class Crop:
    top: float
    bottom: float
    left: float
    right: float

    @property
    def any(self) -> bool:
        return any((self.top, self.bottom, self.left, self.right))

    @property
    def valid(self) -> bool:
        parts = (self.top, self.bottom, self.left, self.right)
        return (
            all(0 <= p < 1 for p in parts)
            and self.top + self.bottom < 1
            and self.left + self.right < 1
        )

    def shape(self, width: int, height: int) -> float:
        """Width over height of the picture once cropped."""
        return (width * (1 - self.left - self.right)) / (height * (1 - self.top - self.bottom))


@dataclass(frozen=True)
class Shape:
    """A picture shape in the drawing records: which stored picture, and its crop."""

    blip: int  # 1-based, into the picture store
    crop: Crop


def _records(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        head, kind, length = struct.unpack_from("<HHI", buf, pos)
        body = pos + 8
        if body + length > end:
            return  # a record claiming more than its parent holds: stop, don't guess
        yield head >> 4, kind, body, length
        # Publisher follows its drawing-group and drawing containers with four
        # more bytes (libmspub's getEscherElementTailLength).
        pos = body + length + (4 if kind in (DGG, DG) else 0)


def _fixed(value: int) -> float:
    """A 16.16 fixed-point fraction, signed."""
    signed = value - (1 << 32) if value >= 1 << 31 else value
    return signed / 65536


def read(buf: bytes) -> tuple[list[int], list[Shape]]:
    """The stored pictures' record sizes, and every picture shape in drawing order."""
    stored: list[int] = []
    shapes: list[Shape] = []

    def walk_shapes(start: int, end: int) -> None:
        for _, kind, body, length in _records(buf, start, end):
            if kind == SPGR:
                walk_shapes(body, body + length)
            elif kind == SP:
                props: dict[int, int] = {}
                for count, inner, ibody, ilength in _records(buf, body, body + length):
                    if inner == FOPT and count * 6 <= ilength:
                        for i in range(count):
                            key, value = struct.unpack_from("<HI", buf, ibody + i * 6)
                            props[key & 0x3FFF] = value
                blip = props.get(PIB) or props.get(FILL_BLIP)
                if blip:
                    shapes.append(Shape(blip, Crop(*(_fixed(props.get(k, 0)) for k in CROP))))

    for _, kind, body, length in _records(buf, 0, len(buf)):
        if kind == DGG:
            for _, inner, ibody, ilength in _records(buf, body, body + length):
                if inner == BSTORE:
                    for _, entry, ebody, elength in _records(buf, ibody, ibody + ilength):
                        if entry == FBSE and elength >= 24:
                            stored.append(struct.unpack_from("<I", buf, ebody + 20)[0])
        elif kind == DG:
            for _, inner, ibody, ilength in _records(buf, body, body + length):
                if inner == SPGR:
                    walk_shapes(ibody, ibody + ilength)
    return stored, shapes


def _asset_for(size: int, assets: list[dict]) -> dict | None:
    """The one asset whose payload is this stored picture, by size."""
    near = [a for a in assets if 0 <= size - a.get("byteLength", -(10**9)) <= SIZE_SLACK]
    return near[0] if len(near) == 1 else None


def crops(bundle: Path, document: dict, assets: dict) -> tuple[dict[str, Crop], list[dict]]:
    """Each image element's crop, by element id, and notes on any not applied."""
    path = bundle / "drawing.bin"
    if not path.is_file():
        return {}, []
    try:
        stored, shapes = read(path.read_bytes())
    except (struct.error, ValueError):
        return {}, [_note("crop-unreadable", "Picture crops could not be read from the file.")]
    by_id = {a["id"]: a for a in assets.get("assets", [])}
    placements: dict[str, list[dict]] = defaultdict(list)
    for page in document.get("pages", []):
        if page.get("kind", "page") != "page":
            continue
        for element in sorted(page.get("elements", []), key=lambda e: e["zIndex"]):
            asset = (element.get("image") or {}).get("assetId")
            if (
                element.get("type") == "image"
                and isinstance(asset, str)
                and asset in by_id
                and element.get("bounds")
            ):
                placements[asset].append(element)
    wanted: dict[str, list[Crop]] = defaultdict(list)
    for shape in shapes:
        if not 0 < shape.blip <= len(stored):
            continue
        asset = _asset_for(stored[shape.blip - 1], list(by_id.values()))
        if asset is not None:
            wanted[asset["id"]].append(shape.crop)

    result: dict[str, Crop] = {}
    notes: list[dict] = []
    for asset_id, uses in placements.items():
        found = wanted.get(asset_id, [])
        if not any(c.any for c in found):
            continue
        if len(found) != len(uses):
            notes.append(_note("crop-unmatched", "A picture's crop could not be matched to it."))
            continue
        asset = by_id[asset_id]
        paired = _pair(uses, found, asset.get("pixelWidth"), asset.get("pixelHeight"))
        if paired is None:
            notes.append(
                _note(
                    "crop-unmatched",
                    "A picture's crop did not fit its frame, so it was left uncropped.",
                )
            )
            continue
        for element, crop in paired:
            if crop.any:
                result[element["id"]] = crop
    return result, notes


def _fits(element: dict, crop: Crop, width: int | None, height: int | None) -> bool:
    if not crop.any:
        return True
    if not crop.valid or not width or not height:
        return False
    bounds = element["bounds"]
    frame = bounds["width"] / bounds["height"]
    return abs(crop.shape(width, height) - frame) <= SHAPE_TOLERANCE * frame


def _pair(uses, found, width, height):
    orders = itertools.permutations(found) if len(found) <= MAX_PERMUTED else [tuple(found)]
    for order in orders:
        pairs = list(zip(uses, order, strict=True))
        if all(_fits(element, crop, width, height) for element, crop in pairs):
            return pairs
    return None


def _note(code: str, message: str) -> dict:
    return {"code": code, "message": message}
