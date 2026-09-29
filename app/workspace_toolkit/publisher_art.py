"""The pictures a Publisher file needs before it can go to Google Slides.

Slides draws a picture only from a PNG, JPEG or GIF it fetches by URL, so
everything that is to become a picture is prepared here first, offline, as
files: the parser's extracted assets (converted or reduced when Slides would
refuse them), drawn paths that no Slides shape can express, and each border
of border art composed into one picture (DECISIONS.md, 2026-09-28).

Nothing here talks to Google. The renderer (`publisher_slides.py`) places
what this prepares; step 3 of the Publisher work delivers the files.
"""

from __future__ import annotations

import math
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from .units import length_points

# Google's documented createImage limits.
SLIDES_MIMES = {"image/png", "image/jpeg", "image/gif"}
SLIDES_MAX_PIXELS = 25_000_000
SLIDES_MAX_BYTES = 50 * 1024 * 1024

PPI = 220  # as for "Make pictures smaller": sharp at print size, no larger
SUPERSAMPLE = 3  # drawn at 3× and reduced, for smooth edges
CURVE_STEPS = 24
DECODE_LIMIT = 60_000_000  # pictures.py's MAX_PIXELS: refuse decompression bombs
GREY = "#808080"


@dataclass
class Picture:
    """A file ready for Slides, and what became of its source."""

    key: str
    path: Path
    width: int
    height: int
    mime: str
    notes: list[dict] = field(default_factory=list)


@dataclass
class Drawn:
    """A picture made from part of the document, with where it goes."""

    picture: Picture
    box: tuple[float, float, float, float]  # x, y, width, height in points


@dataclass
class Prepared:
    pictures: dict[str, Picture] = field(default_factory=dict)  # by asset id
    drawn: dict[str, Drawn] = field(default_factory=dict)  # by element id
    borders: dict[str, Drawn] = field(default_factory=dict)  # by border key
    refused: dict[str, str] = field(default_factory=dict)  # asset id → reason
    cropped: dict[str, Picture] = field(default_factory=dict)  # by element id
    # WordArt recovered from the drawing records, by the layer libmspub drew
    # its outline in: (publisher_wordart.WordArt, its box on the page).
    wordart: dict[str, tuple] = field(default_factory=dict)
    notes: list[dict] = field(default_factory=list)  # about the document as a whole


def note(code: str, message: str) -> dict:
    return {"code": code, "message": message}


# ------------------------------------------------------------------ paths


@dataclass
class Subpath:
    points: list[tuple[float, float]]
    closed: bool = False
    curved: bool = False


def _xy(props: dict, x: str = "svg:x", y: str = "svg:y") -> tuple[float, float] | None:
    px, py = length_points(props.get(x)), length_points(props.get(y))
    return None if px is None or py is None else (px, py)


def subpaths(commands: list[dict]) -> list[Subpath]:
    """The path's pieces as point lists, curves flattened to short segments."""
    result: list[Subpath] = []
    current: Subpath | None = None
    for command in commands:
        action = command.get("action", "").upper()
        props = command.get("properties", {})
        if action == "Z":
            if current and len(current.points) > 1:
                current.closed = True
                start = current.points[0]
                result.append(current)
                current = Subpath([start])
            continue
        end = _xy(props)
        if end is None:
            continue
        if action == "M" or current is None:
            if current and len(current.points) > 1:
                result.append(current)
            current = Subpath([end])
            continue
        start = current.points[-1]
        if action == "L":
            current.points.append(end)
        elif action == "C":
            c1, c2 = _xy(props, "svg:x1", "svg:y1"), _xy(props, "svg:x2", "svg:y2")
            if c1 is None or c2 is None:
                current.points.append(end)
                continue
            current.curved = True
            current.points.extend(_cubic(start, c1, c2, end))
        elif action == "Q":
            c1 = _xy(props, "svg:x1", "svg:y1")
            if c1 is None:
                current.points.append(end)
                continue
            current.curved = True
            current.points.extend(
                _cubic(start, _lerp(start, c1, 2 / 3), _lerp(end, c1, 2 / 3), end)
            )
        elif action == "A":
            current.curved = True
            current.points.extend(_arc(start, end, props))
        else:
            current.points.append(end)
    if current and len(current.points) > 1:
        result.append(current)
    return result


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _cubic(p0, p1, p2, p3):
    points = []
    for i in range(1, CURVE_STEPS + 1):
        t = i / CURVE_STEPS
        s = 1 - t
        points.append(
            (
                s**3 * p0[0] + 3 * s * s * t * p1[0] + 3 * s * t * t * p2[0] + t**3 * p3[0],
                s**3 * p0[1] + 3 * s * s * t * p1[1] + 3 * s * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return points


def _arc(start, end, props):
    """An SVG elliptical arc, by the endpoint-to-centre conversion (SVG 1.1 F.6.5)."""
    rx = abs(length_points(props.get("svg:rx")) or 0)
    ry = abs(length_points(props.get("svg:ry")) or 0)
    if rx == 0 or ry == 0 or start == end:
        return [end]
    phi = math.radians(float(props.get("librevenge:rotate", 0) or 0))
    large = str(props.get("librevenge:large-arc", "false")).lower() in {"true", "1"}
    sweep = str(props.get("librevenge:sweep", "false")).lower() in {"true", "1"}
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - end[0]) / 2, (start[1] - end[1]) / 2
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    scale = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = cos * cx1 - sin * cy1 + (start[0] + end[0]) / 2
    cy = sin * cx1 + cos * cy1 + (start[1] + end[1]) / 2

    def angle(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    theta = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    points = []
    for i in range(1, CURVE_STEPS + 1):
        t = theta + delta * i / CURVE_STEPS
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        points.append((cos * ex - sin * ey + cx, sin * ex + cos * ey + cy))
    return points


def area(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[(i + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


# ------------------------------------------------------------------ styles


def colour(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not value.startswith("#") or len(value) != 7:
        return None
    try:
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    except ValueError:
        return None


def opacity(value: object) -> int:
    if isinstance(value, str) and value.endswith("%"):
        try:
            return max(0, min(255, round(float(value[:-1]) * 2.55)))
        except ValueError:
            pass
    return 255


def paint(style: dict) -> tuple[tuple | None, tuple | None, float, list[dict]]:
    """Fill colour, stroke colour and stroke width (pt) for drawing, with notes."""
    notes = []
    fill: tuple | None = None
    kind = style.get("draw:fill", "none")
    if kind == "solid":
        fill = colour(style.get("draw:fill-color")) or colour(GREY)
    elif kind == "gradient":
        fill = colour(style.get("draw:fill-color")) or colour(style.get("draw:start-color"))
        if fill is None:
            fill = colour(GREY)
        notes.append(
            note(
                "gradient-approximated",
                "A gradient fill was drawn in a single colour: the reader does not pass on "
                "its colours.",
            )
        )
    elif kind not in {"none", ""}:
        fill = colour(style.get("draw:fill-color")) or colour(GREY)
        notes.append(note("fill-approximated", f"A {kind} fill was drawn in a single colour."))
    if fill is not None:
        fill = (*fill, opacity(style.get("draw:opacity")))
    stroke: tuple | None = None
    width = 0.0
    if style.get("draw:stroke", "none") not in {"none", ""}:
        rgb_ = colour(style.get("svg:stroke-color")) or (0, 0, 0)
        stroke = (*rgb_, opacity(style.get("svg:stroke-opacity")))
        width = length_points(style.get("svg:stroke-width")) or 0.75
        if style.get("draw:stroke") == "dash":
            notes.append(note("dash-approximated", "A dashed outline was drawn solid."))
    return fill, stroke, width, notes


# ------------------------------------------------------------------ drawing


def _canvas(box: tuple[float, float, float, float]) -> tuple[float, int, int]:
    """Pixels per point for a box, kept within what Slides accepts."""
    _, _, width, height = box
    scale = PPI / 72
    pixels = width * height * scale * scale
    if pixels > SLIDES_MAX_PIXELS:
        scale *= math.sqrt(SLIDES_MAX_PIXELS / pixels) * 0.99
    return scale, max(1, math.ceil(width * scale)), max(1, math.ceil(height * scale))


def draw_path(key: str, pieces: list[Subpath], style: dict, out: Path) -> Drawn | None:
    """A path as a transparent PNG covering its own extent, or None if it draws nothing."""
    fill, stroke, width, notes = paint(style)
    filled = [p for p in pieces if fill is not None and len(p.points) > 2 and area(p.points) > 0.01]
    if not filled and stroke is None:
        return None
    xs = [x for p in pieces for x, _ in p.points]
    ys = [y for p in pieces for _, y in p.points]
    pad = width / 2 + 1
    box = (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
    scale, w, h = _canvas(box)
    big = SUPERSAMPLE
    image = Image.new("RGBA", (w * big, h * big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    def at(point):
        return ((point[0] - box[0]) * scale * big, (point[1] - box[1]) * scale * big)

    for piece in filled:
        pen.polygon([at(p) for p in piece.points], fill=fill)
    if stroke is not None:
        line = max(1, round(width * scale * big))
        for piece in pieces:
            points = [at(p) for p in piece.points]
            if piece.closed:
                points.append(points[0])
            pen.line(points, fill=stroke, width=line, joint="curve")
    image = image.resize((w, h), Image.Resampling.LANCZOS)
    path = out / f"{key}.png"
    image.save(path, "PNG", optimize=True)
    picture = Picture(key, path, w, h, "image/png", notes)
    return Drawn(picture, box)


def _open(path: Path) -> Image.Image | None:
    Image.MAX_IMAGE_PIXELS = DECODE_LIMIT
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(path)
            image.load()
        return image
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def usable(asset: dict, bundle: Path, out: Path) -> tuple[Picture | None, str | None]:
    """The asset as Slides will take it, or the reason it cannot be."""
    source = bundle / asset["filename"]
    mime = asset.get("mimeType", "")
    width, height = asset.get("pixelWidth"), asset.get("pixelHeight")
    fits = (
        mime in SLIDES_MIMES
        and width
        and height
        and width * height <= SLIDES_MAX_PIXELS
        and asset.get("byteLength", 0) <= SLIDES_MAX_BYTES
    )
    if fits and width and height:
        return Picture(asset["id"], source, int(width), int(height), mime), None
    image = _open(source)
    if image is None:
        return None, f"This {mime or 'picture'} could not be read, so it cannot be placed."
    notes = []
    if mime not in SLIDES_MIMES:
        notes.append(note("picture-converted", f"A {mime} picture was converted to PNG."))
    if image.width * image.height > SLIDES_MAX_PIXELS:
        ratio = math.sqrt(SLIDES_MAX_PIXELS / (image.width * image.height)) * 0.99
        image = image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
        notes.append(
            note("picture-reduced", "A picture too large for Google Slides was made smaller.")
        )
    if image.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
        image = image.convert("RGBA")
    path = out / f"{asset['id']}.png"
    image.save(path, "PNG", optimize=True)
    return Picture(asset["id"], path, image.width, image.height, "image/png", notes), None


# ------------------------------------------------------------------ border art


def is_border_tile(element: dict) -> bool:
    return element.get("type") == "image" and any(
        w.get("code") == "probable-border-art" for w in element.get("warnings", [])
    )


def border_key(element: dict) -> str:
    return f"border_{element['pageIndex']:04d}_{element.get('parentId') or 'page'}"


def compose_border(key: str, tiles: list[dict], images: dict[str, Picture], out: Path) -> Drawn:
    """One picture of every tile in a border, drawn where each tile sits."""
    placed = [t for t in tiles if t.get("bounds") and t["image"].get("assetId") in images]
    xs = [t["bounds"]["x"] for t in placed] + [
        t["bounds"]["x"] + t["bounds"]["width"] for t in placed
    ]
    ys = [t["bounds"]["y"] for t in placed] + [
        t["bounds"]["y"] + t["bounds"]["height"] for t in placed
    ]
    box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    scale, w, h = _canvas(box)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    notes = []
    missing = len(tiles) - len(placed)
    for tile in placed:
        image = _open(images[tile["image"]["assetId"]].path)
        if image is None:
            missing += 1
            continue
        b = tile["bounds"]
        size = (max(1, round(b["width"] * scale)), max(1, round(b["height"] * scale)))
        piece = image.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        if tile.get("rotationDegrees"):
            piece = piece.rotate(
                tile["rotationDegrees"], expand=True, resample=Image.Resampling.BICUBIC
            )
        left = round((b["x"] + b["width"] / 2 - box[0]) * scale - piece.width / 2)
        top = round((b["y"] + b["height"] / 2 - box[1]) * scale - piece.height / 2)
        canvas.alpha_composite(piece, (max(0, left), max(0, top)))
    if missing:
        notes.append(
            note(
                "border-tiles-missing",
                f"{missing} of {len(tiles)} border pieces could not be read and are missing.",
            )
        )
    path = out / f"{key}.png"
    canvas.save(path, "PNG", optimize=True)
    return Drawn(Picture(key, path, w, h, "image/png", notes), box)


# ------------------------------------------------------------------ all of it


def crop_picture(key: str, picture: Picture, crop, out: Path) -> Picture | None:
    """The part of a picture Publisher showed, as its own file: a photograph
    stays JPEG, anything else becomes PNG."""
    image = _open(picture.path)
    if image is None:
        return None
    width, height = image.size
    box = (
        round(width * crop.left),
        round(height * crop.top),
        round(width * (1 - crop.right)),
        round(height * (1 - crop.bottom)),
    )
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        return None
    part = image.crop(box)
    if picture.mime == "image/jpeg":
        path, mime = out / f"{key}.jpg", "image/jpeg"
        part.convert("RGB").save(path, "JPEG", quality=92)
    else:
        path, mime = out / f"{key}.png", "image/png"
        part.save(path, "PNG", optimize=True)
    return Picture(key, path, part.width, part.height, mime, list(picture.notes))


def prepare(
    document: dict, assets: dict, bundle: Path, out: Path, crops: dict | None = None
) -> Prepared:
    """Makes every picture the document needs, under `out`.

    `crops` (publisher_crop) gives the part of a picture each placement shows.
    """
    from .publisher_slides import path_plan  # the renderer decides what is drawn

    out.mkdir(parents=True, exist_ok=True)
    prepared = Prepared()
    for asset in assets.get("assets", []):
        picture, reason = usable(asset, bundle, out)
        if picture is None:
            prepared.refused[asset["id"]] = reason or "unreadable"
        else:
            prepared.pictures[asset["id"]] = picture
    by_element = {
        element["id"]: (element.get("image") or {}).get("assetId")
        for page in document.get("pages", [])
        for element in page.get("elements", [])
    }
    for element_id, crop in (crops or {}).items():
        source = prepared.pictures.get(by_element.get(element_id) or "")
        if source is None:
            continue
        part = crop_picture(f"crop_{element_id}", source, crop, out)
        if part is not None:
            prepared.cropped[element_id] = part
    borders: dict[str, list[dict]] = defaultdict(list)
    for page in document.get("pages", []):
        if page.get("kind", "page") != "page":
            continue
        for element in page.get("elements", []):
            if is_border_tile(element):
                borders[border_key(element)].append(element)
            elif element.get("type") in {"path", "shape", "line"}:
                decision = path_plan(element)
                if decision.kind == "picture":
                    drawn = draw_path(
                        f"drawn_{element['id']}",
                        decision.pieces,
                        element["source"]["styleProperties"],
                        out,
                    )
                    if drawn is not None:
                        prepared.drawn[element["id"]] = drawn
    for key, tiles in borders.items():
        if any(t["image"].get("assetId") in prepared.pictures for t in tiles):
            prepared.borders[key] = compose_border(key, tiles, prepared.pictures, out)
    return prepared
