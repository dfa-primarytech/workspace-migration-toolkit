"""Windows metafile (WMF) clipart, drawn as a picture.

Publisher keeps its clipart as WMF. Pillow opens WMF only on Windows, so off
it every such picture was reported unreadable and left out of the slide.

This draws the part of the format clipart actually uses: filled polygons,
rectangles and ellipses with a solid brush, and outlines with a plain pen.
A metafile that asks for anything else -- text, an embedded bitmap, an arc --
is refused, not drawn without it: a picture missing its words or its photo
looks finished and is wrong, where a missing picture says so.

The file is untrusted, so every size and count is bounded and nothing here
raises: a file that cannot be drawn gives None.
"""

from __future__ import annotations

import struct

from PIL import Image, ImageChops, ImageDraw

PLACEABLE_KEY = 0x9AC6CDD7
MAX_RECORDS = 500_000
MAX_POINTS = 200_000
MAX_SIDE = 1600
SUPERSAMPLE = 2
MAX_OBJECTS = 4096

SET_WINDOW_ORG = 0x020B
SET_WINDOW_EXT = 0x020C
CREATE_BRUSH = 0x02FC
CREATE_PEN = 0x02FA
SELECT_OBJECT = 0x012D
DELETE_OBJECT = 0x01F0
POLYGON = 0x0324
POLYLINE = 0x0325
POLYPOLYGON = 0x0538
RECTANGLE = 0x041B
ELLIPSE = 0x0418
EOF = 0x0000

# Records that only set drawing state, or objects clipart never needs drawn:
# safe to skip because they change nothing that is already on the picture.
HARMLESS = {
    0x0103,  # SetMapMode
    0x0102,  # SetBkMode
    0x0201,  # SetBkColor
    0x0209,  # SetTextColor
    0x0104,  # SetROP2
    0x0106,  # SetPolyFillMode
    0x0107,  # SetStretchBltMode
    0x012E,  # SetTextAlign
    0x001E,  # SaveDC
    0x0127,  # RestoreDC
    0x0214,  # MoveTo
    0x020D,  # SetViewportOrg
    0x020E,  # SetViewportExt
    0x0035,  # RealizePalette
    0x0234,  # SelectPalette
    0x00F7,  # CreatePalette
    0x02FB,  # CreateFontIndirect
    0x012C,  # SelectClipRegion
}
# Creating an object, whatever its kind, takes the lowest free slot.
CREATES = {CREATE_BRUSH, CREATE_PEN, 0x02FB, 0x00F7, 0x01F9, 0x0142, 0x06FF}

NULL_PEN = 5
HOLLOW_BRUSH = 1


def is_wmf(data: bytes) -> bool:
    """Whether these bytes begin a Windows metafile, placeable or not."""
    if len(data) < 18:
        return False
    if struct.unpack_from("<I", data, 0)[0] == PLACEABLE_KEY:
        return True
    kind, header_words = struct.unpack_from("<HH", data, 0)
    return kind in (1, 2) and header_words == 9


def _signed(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def _colour(data: bytes, offset: int) -> tuple[int, int, int, int]:
    r, g, b = data[offset], data[offset + 1], data[offset + 2]
    return r, g, b, 255


def render_wmf(data: bytes) -> Image.Image | None:
    """The metafile as an RGBA picture on a clear background, or None."""
    try:
        return _render(data)
    except (struct.error, IndexError, ValueError, OverflowError, MemoryError):
        return None


def _render(data: bytes) -> Image.Image | None:
    if not is_wmf(data):
        return None
    offset, bounds = 0, None
    if struct.unpack_from("<I", data, 0)[0] == PLACEABLE_KEY:
        left, top, right, bottom = struct.unpack_from("<hhhh", data, 6)
        bounds = (left, top, right - left, bottom - top)
        offset = 22
    offset += 18  # the standard header

    origin = (0, 0)
    extent: tuple[int, int] | None = None
    objects: list[tuple | None] = []
    brush: tuple | None = None
    pen: tuple | None = None
    shapes: list[tuple] = []
    count = 0
    while offset + 6 <= len(data):
        size, function = struct.unpack_from("<IH", data, offset)
        if size < 3 or offset + size * 2 > len(data):
            return None
        count += 1
        if count > MAX_RECORDS:
            return None
        args = offset + 6
        end = offset + size * 2
        offset = end
        if function == EOF:
            break
        if function == SET_WINDOW_ORG:
            origin = (_signed(data, args + 2), _signed(data, args))
        elif function == SET_WINDOW_EXT:
            extent = (_signed(data, args + 2), _signed(data, args))
        elif function in CREATES:
            made: tuple | None = None
            if function == CREATE_BRUSH:
                style = struct.unpack_from("<H", data, args)[0]
                made = ("brush", style, _colour(data, args + 2))
            elif function == CREATE_PEN:
                style = struct.unpack_from("<H", data, args)[0]
                width = abs(_signed(data, args + 2))
                made = ("pen", style, width, _colour(data, args + 6))
            if None in objects:
                objects[objects.index(None)] = made or ("other",)
            elif len(objects) < MAX_OBJECTS:
                objects.append(made or ("other",))
            else:
                return None
        elif function == SELECT_OBJECT:
            index = struct.unpack_from("<H", data, args)[0]
            chosen = objects[index] if index < len(objects) else None
            if chosen and chosen[0] == "brush":
                brush = chosen
            elif chosen and chosen[0] == "pen":
                pen = chosen
        elif function == DELETE_OBJECT:
            index = struct.unpack_from("<H", data, args)[0]
            if index < len(objects):
                objects[index] = None
        elif function == POLYGON:
            n = struct.unpack_from("<h", data, args)[0]
            ring = _points(data, args + 2, n, end)
            shapes.append(("polygon", [ring], brush, pen))
        elif function == POLYLINE:
            n = struct.unpack_from("<h", data, args)[0]
            ring = _points(data, args + 2, n, end)
            shapes.append(("line", [ring], None, pen))
        elif function == POLYPOLYGON:
            rings = struct.unpack_from("<h", data, args)[0]
            if rings < 0 or rings > MAX_POINTS:
                return None
            sizes = struct.unpack_from(f"<{rings}h", data, args + 2)
            at, parts = args + 2 + rings * 2, []
            if sum(sizes) > MAX_POINTS:
                return None
            for n in sizes:
                parts.append(_points(data, at, n, end))
                at += max(n, 0) * 4
            shapes.append(("polygon", parts, brush, pen))
        elif function in (RECTANGLE, ELLIPSE):
            bottom, right, top, left = struct.unpack_from("<4h", data, args)
            kind = "rectangle" if function == RECTANGLE else "ellipse"
            shapes.append((kind, [[(left, top), (right, bottom)]], brush, pen))
        elif function not in HARMLESS:
            return None  # text, a bitmap, an arc: not something to leave out

    if extent is None and bounds is not None:
        origin, extent = (bounds[0], bounds[1]), (bounds[2], bounds[3])
    if extent is None or extent[0] == 0 or extent[1] == 0 or not shapes:
        return None
    return _paint(shapes, origin, extent)


def _points(data: bytes, offset: int, n: int, end: int) -> list[tuple[int, int]]:
    if n < 0 or n > MAX_POINTS or offset + n * 4 > end:
        raise ValueError("points run past their record")
    return [struct.unpack_from("<hh", data, offset + i * 4) for i in range(n)]


def _paint(shapes: list[tuple], origin: tuple[int, int], extent: tuple[int, int]) -> Image.Image:
    wide, tall = abs(extent[0]), abs(extent[1])
    scale = min(MAX_SIDE / max(wide, tall), 8.0)
    width, height = max(1, round(wide * scale)), max(1, round(tall * scale))
    big = SUPERSAMPLE
    layer = Image.new("RGBA", (width * big, height * big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    def place(x: int, y: int) -> tuple[float, float]:
        # Dividing by a negative extent already runs that axis the other way,
        # which is what a negative extent means.
        return (
            (x - origin[0]) / extent[0] * width * big,
            (y - origin[1]) / extent[1] * height * big,
        )

    for kind, rings, brush, pen in shapes:
        fill = None
        if brush and brush[1] != HOLLOW_BRUSH:
            fill = brush[2]
        outline, line = None, 1
        if pen and pen[1] != NULL_PEN:
            outline, line = pen[3], max(1, round(pen[2] * scale * big))
        if kind == "polygon":
            # Rings are painted even-odd: a ring inside another is a hole.
            if len(rings) > 1 and fill:
                mask = _even_odd(rings, place, layer.size)
                layer.paste(Image.new("RGBA", layer.size, fill), (0, 0), mask)
                fill = None
            for ring in rings:
                path = [place(x, y) for x, y in ring]
                if len(path) >= 3 and (fill or outline):
                    draw.polygon(path, fill=fill, outline=None)
                if outline and len(path) >= 2:
                    draw.line([*path, path[0]], fill=outline, width=line)
        elif kind == "line":
            path = [place(x, y) for x, y in rings[0]]
            if outline and len(path) >= 2:
                draw.line(path, fill=outline, width=line)
        else:
            (x1, y1), (x2, y2) = rings[0]
            (ax, ay), (bx, by) = place(x1, y1), place(x2, y2)
            box = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
            shape = draw.rectangle if kind == "rectangle" else draw.ellipse
            shape(box, fill=fill, outline=outline, width=line if outline else 0)
    # Premultiplied, so a soft edge does not pick up the clear pixels' black.
    small = layer.convert("RGBa").resize((width, height), Image.Resampling.LANCZOS)
    return small.convert("RGBA")


def _even_odd(rings, place, size) -> Image.Image:
    """A mask where rings overlapping an odd number of times are filled."""
    mask = Image.new("L", size, 0)
    for ring in rings:
        path = [place(x, y) for x, y in ring]
        if len(path) < 3:
            continue
        one = Image.new("L", size, 0)
        ImageDraw.Draw(one).polygon(path, fill=255)
        mask = _xor(mask, one)
    return mask


def _xor(a: Image.Image, b: Image.Image) -> Image.Image:
    return ImageChops.logical_xor(a.convert("1"), b.convert("1")).convert("L")
