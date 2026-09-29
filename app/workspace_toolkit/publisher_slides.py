"""A Publisher document, as Google Slides API requests (Publisher step 2).

`plan()` turns the parser's IR, plus the pictures `publisher_art.prepare()`
made, into:

- the body for `presentations.create`, at the publication's own page size
  (PROJECT.md §13);
- the requests that make one blank slide per page;
- one list of `batchUpdate` requests per page, in paint order, so the last
  thing Publisher drew is on top;
- a report line for every element, saying what it became (§16: nothing is
  dropped without saying so).

It is pure: no files, no network. Pictures are referenced by key as
`wmt-picture:<key>` and swapped for real links by `bind()` just before a page
is sent, because the signed links Slides fetches them through expire quickly
(DECISIONS.md, 2026-09-28).

Every statement here about how Google draws a request is unverified until the
live run with PUB-001 (step 4). Statuses are this renderer's plan, not a
measured result, and the report says so.
"""

from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .fonts import FontStatus, catalogue, compatibility
from .model import Compatibility as C
from .publisher_art import (
    Picture,
    Prepared,
    Subpath,
    area,
    border_key,
    colour,
    is_border_tile,
    opacity,
    paint,
    subpaths,
)
from .publisher_fit import (
    INSET_X,
    INSET_Y,
    LINE,
    SAFETY,
    Fit,
    Para,
    Style,
    advance,
    fit,
    measurable,
)
from .publisher_wrap import Obstacle, wrap
from .units import Frame, length_points, percentage, size

PICTURE = "wmt-picture:"
PREFIX = "wmt_"
OBJECT_ID = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-:]{4,49}$")
MIN_COLUMN_WIDTH = 32.0  # points; narrower columns are refused (unverified)
LINE_MINIMUM = 0.01  # points: a horizontal or vertical line still needs some extent
UNGROUPABLE = {"table"}
ALIGNMENT = {
    "left": "START",
    "start": "START",
    "center": "CENTER",
    "right": "END",
    "end": "END",
    "justify": "JUSTIFIED",
}
VERTICAL = {"top": "TOP", "middle": "MIDDLE", "center": "MIDDLE", "bottom": "BOTTOM"}
BASIS = "Planned from the reader's output; not yet checked against Google Slides."


def oid(*parts: object) -> str:
    """A Slides object ID: letters, digits, '_', '-' and ':', 5 to 50 long."""
    text = PREFIX + "_".join(re.sub(r"[^a-zA-Z0-9_\-:]", "_", str(p)) for p in parts)
    return text[:50]


def utf16(text: str) -> int:
    """Slides counts text in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def note(code: str, message: str) -> dict:
    return {"code": code, "message": message}


# ------------------------------------------------------------------ the plan


@dataclass
class Line:
    """What happened to one element."""

    element_id: str
    page_index: int
    type: str
    status: str
    objects: list[str] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "elementId": self.element_id,
            "pageIndex": self.page_index,
            "type": self.type,
            "status": str(self.status),
            "objects": self.objects,
            "notes": self.notes,
        }


@dataclass
class Plan:
    create: dict
    setup: list[dict]
    pages: list[list[dict]]
    pictures: dict[str, Picture]
    slides: list[str]
    report: dict

    def as_dict(self, root: Path) -> dict:
        """For plan.json: the worker writes it, the app sends it."""
        return {
            "create": self.create,
            "setup": self.setup,
            "pages": self.pages,
            "slides": self.slides,
            "report": self.report,
            "pictures": {
                key: {
                    "path": picture.path.relative_to(root).as_posix(),
                    "width": picture.width,
                    "height": picture.height,
                    "mime": picture.mime,
                }
                for key, picture in self.pictures.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict, root: Path) -> Plan:
        pictures = {}
        for key, item in data["pictures"].items():
            path = (root / item["path"]).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("a picture outside the job")
            pictures[key] = Picture(key, path, item["width"], item["height"], item["mime"])
        return cls(
            data["create"], data["setup"], data["pages"], pictures, data["slides"], data["report"]
        )

    def keys_for(self, page: int) -> list[str]:
        """The pictures a page's requests need links for."""
        return sorted(
            {
                r["createImage"]["url"][len(PICTURE) :]
                for r in self.pages[page]
                if "createImage" in r and r["createImage"]["url"].startswith(PICTURE)
            }
        )


def bind(requests: list[dict], urls: dict[str, str]) -> list[dict]:
    """The requests with each picture key replaced by its link."""
    bound = copy.deepcopy(requests)
    for request in bound:
        image = request.get("createImage")
        if image and image["url"].startswith(PICTURE):
            key = image["url"][len(PICTURE) :]
            if key not in urls:
                raise KeyError(f"no link for picture {key}")
            image["url"] = urls[key]
    return bound


# ------------------------------------------------------------------ styles


def rgb(value: tuple[int, int, int]) -> dict:
    red, green, blue = value
    return {"rgbColor": {"red": red / 255, "green": green / 255, "blue": blue / 255}}


def solid(value: tuple, alpha: int = 255) -> dict:
    return {"solidFill": {"color": rgb(value[:3]), "alpha": round(alpha / 255, 4)}}


def box_style(object_id: str, style: dict, *, text: bool) -> tuple[list[dict], list[dict]]:
    """Fill and outline for a shape or text box, as Publisher painted it."""
    fill, stroke, width, notes = paint(style)
    properties: dict = {}
    if fill is None:
        properties["shapeBackgroundFill"] = {"propertyState": "NOT_RENDERED"}
    else:
        properties["shapeBackgroundFill"] = solid(fill, fill[3])
    if stroke is None:
        properties["outline"] = {"propertyState": "NOT_RENDERED"}
    else:
        properties["outline"] = {
            "outlineFill": solid(stroke, stroke[3]),
            "weight": {"magnitude": round(width, 4), "unit": "PT"},
            "dashStyle": "DASH" if style.get("draw:stroke") == "dash" else "SOLID",
        }
        notes = [n for n in notes if n["code"] != "dash-approximated"]
    fields = ["shapeBackgroundFill", "outline"]
    vertical = VERTICAL.get(str(style.get("draw:textarea-vertical-align", "")).lower())
    if text and vertical:
        properties["contentAlignment"] = vertical
        fields.append("contentAlignment")
    request = {
        "updateShapeProperties": {
            "objectId": object_id,
            "shapeProperties": properties,
            "fields": ",".join(fields),
        }
    }
    return [request], notes


def resolve_font(family: str | None, fonts: dict[str, dict]) -> str | None:
    """The family Slides should use, by the shared font service's decision."""
    if not family:
        return None
    record = fonts.setdefault(family, compatibility(family))
    if record["status"] == FontStatus.SUBSTITUTED and record.get("replacement"):
        return str(record["replacement"])
    if record["status"] == FontStatus.AVAILABLE and record.get("replacement"):
        return str(record["replacement"])  # the catalogue's own spelling
    return str(record["name"])


def run_style(style: dict, props: dict, fonts: dict[str, dict]) -> tuple[dict, list[str]]:
    result: dict = {}
    fields: list[str] = []
    family = resolve_font(style.get("fontFamily"), fonts)
    if family:
        result["fontFamily"] = family
        fields.append("fontFamily")
    if style.get("fontSizePoints"):
        result["fontSize"] = {"magnitude": style["fontSizePoints"], "unit": "PT"}
        fields.append("fontSize")
    for key in ("bold", "italic"):
        result[key] = bool(style.get(key))
        fields.append(key)
    underline = style.get("underline")
    result["underline"] = bool(underline) and underline != "none"
    fields.append("underline")
    strike = props.get("style:text-line-through-type") or props.get("style:text-line-through-style")
    if strike:
        result["strikethrough"] = strike != "none"
        fields.append("strikethrough")
    if props.get("fo:font-variant") == "small-caps":
        result["smallCaps"] = True
        fields.append("smallCaps")
    position = str(props.get("style:text-position", ""))
    if position.startswith(("super", "33%")):
        result["baselineOffset"] = "SUPERSCRIPT"
        fields.append("baselineOffset")
    elif position.startswith(("sub", "-33%")):
        result["baselineOffset"] = "SUBSCRIPT"
        fields.append("baselineOffset")
    tint = colour(style.get("color"))
    if tint:
        result["foregroundColor"] = {"opaqueColor": rgb(tint)}
        fields.append("foregroundColor")
    return result, fields


def paragraph_style(paragraph: dict) -> tuple[dict, list[str], list[dict]]:
    props = paragraph.get("sourceProperties") or {}
    result: dict = {}
    fields: list[str] = []
    notes: list[dict] = []
    alignment = ALIGNMENT.get(str(paragraph["style"].get("alignment") or "").lower())
    if alignment:
        result["alignment"] = alignment
        fields.append("alignment")
    start = length_points(props.get("fo:margin-left")) or 0.0
    first = start + (length_points(props.get("fo:text-indent")) or 0.0)
    if start or first:
        result["indentStart"] = {"magnitude": round(max(0.0, start), 4), "unit": "PT"}
        result["indentFirstLine"] = {"magnitude": round(max(0.0, first), 4), "unit": "PT"}
        fields += ["indentStart", "indentFirstLine"]
    end = length_points(props.get("fo:margin-right"))
    if end:
        result["indentEnd"] = {"magnitude": round(max(0.0, end), 4), "unit": "PT"}
        fields.append("indentEnd")
    for source, target in (("fo:margin-top", "spaceAbove"), ("fo:margin-bottom", "spaceBelow")):
        value = length_points(props.get(source))
        if value:
            result[target] = {"magnitude": round(max(0.0, value), 4), "unit": "PT"}
            fields.append(target)
    height = props.get("fo:line-height")
    if percentage(height):
        result["lineSpacing"] = percentage(height)
        fields.append("lineSpacing")
    elif height is not None and length_points(height):
        notes.append(
            note(
                "line-spacing-exact",
                "Exact line spacing has no equivalent in Google Slides, so normal spacing is used.",
            )
        )
    return result, fields, notes


# Characters Slides drops or merges on insert, which would shift every text
# range after them. The reader leaves Publisher's own paragraph mark (a
# carriage return) at the end of each paragraph's text: found by the first live
# run, where Google refused every page because the ranges overran the text.
# Tabs stay, and line breaks inside a paragraph are written as vertical tabs.
DROPPED = {chr(c) for c in range(32) if chr(c) not in "\t\u000b"} | {"\u007f"}


def clean(text: str) -> str:
    return "".join(ch for ch in text if ch not in DROPPED)


def paragraph_text(paragraph: dict) -> list[tuple[str, dict]]:
    """Each run's text as Slides should receive it."""
    pieces = []
    for run in paragraph.get("runs", []):
        items = run.get("items")
        if not items:
            text = run.get("text", "")
        else:
            text = ""
            for item in items:
                kind = item.get("kind")
                if kind == "tab":
                    text += "\t"
                elif kind == "lineBreak":
                    text += "\u000b"  # a line break inside a paragraph
                elif kind == "space":
                    text += item.get("value") or " "
                elif kind == "text":
                    text += item.get("value", "")
        pieces.append((clean(text.replace("\n", "\u000b")), run))
    return pieces


def _laid(paragraphs: list[dict]) -> tuple[list[dict], list[list[tuple[str, dict]]]]:
    laid = [paragraph_text(p) for p in paragraphs]
    while laid and not "".join(t for t, _ in laid[-1]):
        laid.pop()  # a trailing empty paragraph adds nothing Slides can show
    return paragraphs[: len(laid)], laid


def measured(paragraphs: list[dict], fonts: dict[str, dict]) -> list[Para]:
    """The text as publisher_fit lays it out: in the fonts Slides will use."""
    paragraphs, laid = _laid(paragraphs)
    result = []
    for paragraph, pieces in zip(paragraphs, laid, strict=True):
        style, _, _ = paragraph_style(paragraph)
        points = {k: float(v["magnitude"]) for k, v in style.items() if isinstance(v, dict)}

        runs = [
            (
                text,
                Style(
                    resolve_font(run["style"].get("fontFamily"), fonts),
                    float(run["style"].get("fontSizePoints") or 12),
                    bool(run["style"].get("bold")),
                    bool(run["style"].get("italic")),
                ),
            )
            for text, run in pieces
        ]
        result.append(
            Para(
                runs,
                points.get("indentStart", 0.0),
                points.get("indentFirstLine", 0.0),
                points.get("indentEnd", 0.0),
                points.get("spaceAbove", 0.0),
                points.get("spaceBelow", 0.0),
                style.get("lineSpacing"),
            )
        )
    return result


def text_requests(
    object_id: str,
    paragraphs: list[dict],
    fonts: dict[str, dict],
    cell: dict | None = None,
    fitted: Fit | None = None,
    extra: dict[int, tuple[float, float]] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Insert the text, then style each run and paragraph by its range.

    `fitted` (publisher_fit) makes the text fit its box: its scale applies to
    every font size, and its line spacing to every paragraph. `extra`
    (publisher_wrap) adds start and end indents to paragraphs beside a picture.
    """
    paragraphs, laid = _laid(paragraphs)
    scale = fitted.scale if fitted else 1.0
    spacing = fitted.line_spacing if fitted else None
    whole = "\n".join("".join(t for t, _ in pieces) for pieces in laid)
    notes: list[dict] = []
    if any(i.get("kind") == "field" for p in paragraphs for r in p["runs"] for i in r["items"]):
        notes.append(note("field-dropped", "A field (such as a page number) has no value to show."))
    if not whole:
        return [], notes
    where: dict[str, object] = {"objectId": object_id}
    if cell is not None:
        where["cellLocation"] = cell
    total = utf16(whole)
    requests: list[dict] = [{"insertText": {**where, "insertionIndex": 0, "text": whole}}]
    position = 0
    for number, (paragraph, pieces) in enumerate(zip(paragraphs, laid, strict=True)):
        start = position
        for text, run in pieces:
            length = utf16(text)
            if length:
                style, fields = run_style(run["style"], run.get("sourceProperties") or {}, fonts)
                requests.append(
                    _styled(where, position, position + length, _scaled(style, scale), fields)
                )
            position += length
        if position == start and start < total and pieces:
            # An empty paragraph is as tall as its font: style its line break.
            _, run = pieces[0]
            style, fields = run_style(run["style"], run.get("sourceProperties") or {}, fonts)
            requests.append(_styled(where, start, start + 1, _scaled(style, scale), fields))
        style, fields, more = paragraph_style(paragraph)
        notes += more
        if spacing is not None and spacing < style.get("lineSpacing", 100):
            style["lineSpacing"] = spacing
            if "lineSpacing" not in fields:
                fields.append("lineSpacing")
        added = (extra or {}).get(number)
        if added:
            _indent(style, fields, *added)
        if fields:
            end = position if position > start else min(start + 1, total)
            requests.append(
                {
                    "updateParagraphStyle": {
                        **where,
                        "textRange": {"type": "FIXED_RANGE", "startIndex": start, "endIndex": end},
                        "style": style,
                        "fields": ",".join(fields),
                    }
                }
            )
        position += 1  # the paragraph break
    return requests, _unique(notes)


def _indent(style: dict, fields: list[str], start: float, end: float) -> None:
    """Adds to a paragraph's indents, keeping its first line's offset."""
    for key, amount in (("indentStart", start), ("indentFirstLine", start), ("indentEnd", end)):
        if not amount:
            continue
        current = style.get(key, {}).get("magnitude", 0.0)
        style[key] = {"magnitude": round(current + amount, 4), "unit": "PT"}
        if key not in fields:
            fields.append(key)


def _scaled(style: dict, scale: float) -> dict:
    """Font sizes times `scale`, to the nearest half point."""
    if scale == 1.0 or "fontSize" not in style:
        return style
    size = style["fontSize"]["magnitude"]
    return {**style, "fontSize": {"magnitude": round(size * scale * 2) / 2, "unit": "PT"}}


def _styled(where: dict[str, object], start: int, end: int, style: dict, fields: list[str]) -> dict:
    return {
        "updateTextStyle": {
            **where,
            "textRange": {"type": "FIXED_RANGE", "startIndex": start, "endIndex": end},
            "style": style,
            "fields": ",".join(fields),
        }
    }


def _unique(notes: Iterable[dict]) -> list[dict]:
    seen, result = set(), []
    for item in notes:
        if item["code"] not in seen:
            seen.add(item["code"])
            result.append(item)
    return result


# ------------------------------------------------------------------ geometry


def frame_of(element: dict) -> Frame | None:
    """Where an element sits: its true frame if it is turned, else its bounds."""
    outline = (element.get("image") or {}).get("polygon") or (element.get("geometry") or {}).get(
        "points"
    )
    rotation = element.get("rotationDegrees") or 0.0
    if (
        outline
        and rotation
        and any(w["code"] == "rotation-from-outline" for w in element.get("warnings", []))
    ):
        frame = Frame.from_outline([(p["x"], p["y"]) for p in outline])
        if frame is not None:
            return frame
    bounds = element.get("bounds")
    if bounds:
        return Frame.from_bounds(
            bounds["x"], bounds["y"], bounds["width"], bounds["height"], rotation
        )
    props = element["source"]["properties"]
    cx, cy = length_points(props.get("svg:cx")), length_points(props.get("svg:cy"))
    rx, ry = length_points(props.get("svg:rx")), length_points(props.get("svg:ry"))
    if cx is not None and cy is not None and rx is not None and ry is not None:
        return Frame(2 * rx, 2 * ry, cx, cy, rotation)
    return None


@dataclass
class PathPlan:
    """What a drawn element becomes: a Slides shape, lines, a picture, or nothing."""

    kind: str  # "shape" | "lines" | "picture" | "nothing"
    pieces: list[Subpath] = field(default_factory=list)


def _points(element: dict) -> list[Subpath]:
    geometry = element.get("geometry") or {}
    if geometry.get("path"):
        return subpaths(geometry["path"])
    points: list[tuple[float, float]] = [(p["x"], p["y"]) for p in geometry.get("points", [])]
    if not points:
        props = element["source"]["properties"]
        for i in (1, 2):
            x, y = length_points(props.get(f"svg:x{i}")), length_points(props.get(f"svg:y{i}"))
            if x is not None and y is not None:
                points.append((x, y))
    closed = element.get("type") == "shape" and len(points) > 2
    if closed and points[0] == points[-1]:
        points = points[:-1]
    return [Subpath(points, closed=closed)] if len(points) > 1 else []


def path_plan(element: dict) -> PathPlan:
    kind = (element.get("geometry") or {}).get("shapeKind")
    if element.get("type") == "shape" and kind in {"rectangle", "ellipse"}:
        return PathPlan("shape")
    pieces = _points(element)
    if not pieces:
        return PathPlan("nothing")
    fill, stroke, _, _ = paint(element["source"]["styleProperties"])
    filled = fill is not None and any(len(p.points) > 2 and area(p.points) > 0.01 for p in pieces)
    if filled:
        return PathPlan("picture", pieces)
    if stroke is None:
        return PathPlan("nothing", pieces)
    if any(p.curved for p in pieces):
        return PathPlan("picture", pieces)
    return PathPlan("lines", pieces)


def segments(pieces: list[Subpath]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    result = []
    for piece in pieces:
        points = piece.points + ([piece.points[0]] if piece.closed else [])
        result += [(a, b) for a, b in zip(points, points[1:], strict=False) if a != b]
    return result


def line_request(object_id: str, page: str, start, end) -> dict:
    """A straight line from `start` to `end`: its box, flipped to point the right way."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    return {
        "createLine": {
            "objectId": object_id,
            "lineCategory": "STRAIGHT",
            "elementProperties": {
                "pageObjectId": page,
                "size": size(max(abs(dx), LINE_MINIMUM), max(abs(dy), LINE_MINIMUM)),
                "transform": {
                    "scaleX": -1.0 if dx < 0 else 1.0,
                    "scaleY": -1.0 if dy < 0 else 1.0,
                    "shearX": 0.0,
                    "shearY": 0.0,
                    "translateX": round(start[0], 6),
                    "translateY": round(start[1], 6),
                    "unit": "PT",
                },
            },
        }
    }


def line_style(object_id: str, style: dict) -> dict:
    _, stroke, width, _ = paint(style)
    stroke = stroke or (0, 0, 0, 255)
    return {
        "updateLineProperties": {
            "objectId": object_id,
            "lineProperties": {
                "lineFill": solid(stroke, stroke[3]),
                "weight": {"magnitude": round(width, 4), "unit": "PT"},
                "dashStyle": "DASH" if style.get("draw:stroke") == "dash" else "SOLID",
            },
            "fields": "lineFill,weight,dashStyle",
        }
    }


def image_request(object_id: str, page: str, picture: Picture, frame: Frame) -> dict:
    """The picture stretched to fill its frame, as Publisher's bitmap fill does.

    Slides fits a picture inside the size it is given without distorting it,
    so the size given keeps the picture's own shape, and the transform
    stretches it to the frame.
    """
    width = frame.width
    height = frame.width * picture.height / picture.width
    return {
        "createImage": {
            "objectId": object_id,
            "url": PICTURE + picture.key,
            "elementProperties": {
                "pageObjectId": page,
                "size": size(width, height),
                "transform": frame.transform(width, height),
            },
        }
    }


def placed(object_id: str, page: str, frame: Frame) -> dict:
    return {
        "pageObjectId": page,
        "size": size(frame.width, frame.height),
        "transform": frame.transform(frame.width, frame.height),
    }


# ------------------------------------------------------------------ elements


def hidden_borders(object_id: str) -> dict:
    """Every border of a table, made invisible."""
    return {
        "updateTableBorderProperties": {
            "objectId": object_id,
            "borderPosition": "ALL",
            "tableBorderProperties": {
                "tableBorderFill": {"solidFill": {"color": rgb((0, 0, 0)), "alpha": 0}}
            },
            "fields": "tableBorderFill",
        }
    }


def wordart_size(art, lines: list[str], family: str | None, frame: Frame) -> float:
    """The largest size, to half a point, at which WordArt's lines fill its box.

    WordArt is stretched to its box in Publisher; Slides can't stretch letters,
    so the text is made as large as fits both ways, and no larger than its own
    size said.
    """
    tall = (frame.height - 2 * INSET_Y) / (len(lines) * LINE)
    wide = float("inf")
    if family and measurable(family):
        one = Style(family, 1.0, art.bold, art.italic)
        widest = max(sum(advance(ch, one, 1.0) for ch in line) for line in lines)
        if widest:
            wide = (frame.width - 2 * INSET_X) * SAFETY / widest
    size = min(tall, wide, art.size or float("inf"))
    return max(6.0, int(size * 2) / 2)


def missing_picture(object_id: str, where: dict) -> list[dict]:
    """A dashed box saying a picture could not be converted, where it was."""
    return [
        {
            "createShape": {
                "objectId": object_id,
                "shapeType": "RECTANGLE",
                "elementProperties": where,
            }
        },
        {
            "updateShapeProperties": {
                "objectId": object_id,
                "shapeProperties": {
                    "shapeBackgroundFill": {"propertyState": "NOT_RENDERED"},
                    "outline": {
                        "outlineFill": solid((192, 0, 0)),
                        "weight": {"magnitude": 1, "unit": "PT"},
                        "dashStyle": "DASH",
                    },
                },
                "fields": "shapeBackgroundFill,outline",
            }
        },
        {
            "insertText": {
                "objectId": object_id,
                "insertionIndex": 0,
                "text": "A picture from the original could not be converted.",
            }
        },
    ]


class PageBuilder:
    def __init__(self, page: dict, slide: str, prepared: Prepared, fonts: dict[str, dict]):
        self.page = page
        self.slide = slide
        self.prepared = prepared
        self.fonts = fonts
        self.requests: list[dict] = []
        self.lines: dict[str, Line] = {}
        self.objects: dict[str, list[str]] = {}  # element id → the objects standing for it
        self.pictures: dict[str, Picture] = {}
        self.borders_done: set[str] = set()

    def line(self, element: dict, status: str, *notes: dict) -> Line:
        entry = Line(element["id"], element["pageIndex"], element["type"], status)
        entry.notes += [n for n in notes if n]
        entry.notes += [
            note(w["code"], w["message"])
            for w in element.get("warnings", [])
            if w["code"] not in SETTLED
        ]
        self.lines[element["id"]] = entry
        return entry

    def made(self, element: dict, entry: Line, *objects: str) -> None:
        entry.objects += objects
        self.objects[element["id"]] = list(objects)

    def build(self) -> None:
        elements = sorted(self.page.get("elements", []), key=lambda e: e["zIndex"])
        for element in elements:
            if not element.get("visible", True):
                self.line(element, C.IGNORED, note("hidden", "Hidden in the original."))
                continue
            handler = getattr(self, "_" + element["type"], self._unknown)
            if is_border_tile(element):
                handler = self._border_tile
            if element["id"] in self.prepared.wordart:
                handler = self._wordart
            elif element.get("parentId") in self.prepared.wordart:
                self.line(
                    element,
                    C.IGNORED,
                    note("wordart-outline", "Part of WordArt, which is now text."),
                )
                continue
            handler(element)
        self.group_all(elements)

    # -- one per element type

    def _text(self, element: dict) -> None:
        frame = frame_of(element)
        if frame is None:
            self.line(element, C.UNSUPPORTED, note("no-position", "It has no position."))
            return
        object_id = oid(element["id"])
        self.requests.append(
            {
                "createShape": {
                    "objectId": object_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": placed(object_id, self.slide, frame),
                }
            }
        )
        style, notes = box_style(object_id, element["source"]["styleProperties"], text=True)
        self.requests += style
        paragraphs = element.get("paragraphs", [])
        paras = measured(paragraphs, self.fonts)
        wrapped = None
        if not frame.rotation:
            box = (
                frame.cx - frame.width / 2,
                frame.cy - frame.height / 2,
                frame.width,
                frame.height,
            )
            wrapped = wrap(paras, box, self.in_front_of(element))
        fitted = wrapped.fitted if wrapped else fit(paras, frame.width, frame.height)
        text, more = text_requests(
            object_id,
            paragraphs,
            self.fonts,
            fitted=fitted,
            extra=wrapped.extra if wrapped else None,
        )
        self.requests += text
        if fitted:
            notes = [*notes, *fitted.notes]
        if wrapped and wrapped.around and wrapped.extra:
            count = len(wrapped.around)
            notes.append(
                note(
                    "text-wrapped",
                    f"Text was indented to keep clear of {count} "
                    f"picture{'s' if count > 1 else ''}, as it wrapped around "
                    f"{'them' if count > 1 else 'it'} in the original.",
                )
            )
        if wrapped and wrapped.under:
            notes.append(
                note(
                    "text-under-picture",
                    "A picture covers most of this text's width, so it can't be kept "
                    "clear: it sits over the text, as Slides can't wrap text around it.",
                )
            )
        substituted = any(
            self.fonts[f]["status"] != FontStatus.AVAILABLE
            for f in _families(element.get("paragraphs", []))
            if f in self.fonts
        )
        entry = self.line(element, C.SUBSTITUTED if substituted else C.NATIVE, *notes, *more)
        if substituted:
            entry.notes.append(note("font-substituted", "A font was replaced; see the fonts."))
        self.made(element, entry, object_id)

    def in_front_of(self, element: dict) -> list[Obstacle]:
        """Pictures and shapes drawn over a text frame: Publisher wraps text around them."""
        out = []
        for other in self.page.get("elements", []):
            if (
                other["zIndex"] <= element["zIndex"]
                or not other.get("visible", True)
                or other.get("type") not in {"image", "shape"}
                or is_border_tile(other)
            ):
                continue
            frame = frame_of(other)
            if frame is None:
                continue
            xs = [x for x, _ in frame.corners()]
            ys = [y for _, y in frame.corners()]
            out.append(Obstacle(other["id"], min(xs), min(ys), max(xs), max(ys)))
        return out

    def _image(self, element: dict) -> None:
        frame = frame_of(element)
        asset = (element.get("image") or {}).get("assetId")
        cropped = self.prepared.cropped.get(element["id"])
        picture = cropped or self.prepared.pictures.get(asset or "")
        if frame is None:
            self.line(element, C.UNSUPPORTED, note("no-position", "It has no position."))
            return
        if picture is None:
            reason = self.prepared.refused.get(asset or "", "The picture was not extracted.")
            self._missing(element, frame, reason)
            return
        object_id = oid(element["id"])
        self.requests.append(image_request(object_id, self.slide, picture, frame))
        self.pictures[picture.key] = picture
        status = element["compatibility"]["status"]
        entry = self.line(element, C.NATIVE if status == C.NATIVE else status, *picture.notes)
        if cropped:
            entry.notes.append(note("picture-cropped", "Cropped as in the original."))
        shape = frame.width / frame.height
        if abs(picture.width / picture.height - shape) > 0.02 * shape:
            entry.notes.append(
                note(
                    "picture-stretched",
                    "The picture is stretched to fit its frame. If it looks squashed, check it "
                    "against the original.",
                )
            )
        self.made(element, entry, object_id)

    def _missing(self, element: dict, frame: Frame, reason: str) -> None:
        """A marked space where a picture could not go, so it is not lost silently."""
        object_id = oid(element["id"])
        self.requests += missing_picture(object_id, placed(object_id, self.slide, frame))
        entry = self.line(element, C.UNSUPPORTED, note("picture-missing", reason))
        self.made(element, entry, object_id)

    def _border_tile(self, element: dict) -> None:
        key = border_key(element)
        drawn = self.prepared.borders.get(key)
        if drawn is None:
            self.line(
                element,
                C.UNSUPPORTED,
                note("border-missing", "This border art could not be read."),
            )
            return
        entry = self.line(
            element,
            C.FLATTENED,
            note("border-composed", "Border art was combined into one picture."),
        )
        if key in self.borders_done:
            entry.objects.append(oid(key))
            self.objects[element["id"]] = []
            return
        self.borders_done.add(key)
        x, y, width, height = drawn.box
        object_id = oid(key)
        self.requests.append(
            image_request(
                object_id, self.slide, drawn.picture, Frame.from_bounds(x, y, width, height)
            )
        )
        self.pictures[drawn.picture.key] = drawn.picture
        entry.notes += drawn.picture.notes
        self.made(element, entry, object_id)

    def _shape(self, element: dict) -> None:
        decision = path_plan(element)
        if decision.kind != "shape":
            self._drawn(element, decision)
            return
        frame = frame_of(element)
        if frame is None:
            self.line(element, C.UNSUPPORTED, note("no-position", "It has no position."))
            return
        object_id = oid(element["id"])
        kind = "ELLIPSE" if element["geometry"]["shapeKind"] == "ellipse" else "RECTANGLE"
        self.requests.append(
            {
                "createShape": {
                    "objectId": object_id,
                    "shapeType": kind,
                    "elementProperties": placed(object_id, self.slide, frame),
                }
            }
        )
        style, notes = box_style(object_id, element["source"]["styleProperties"], text=False)
        self.requests += style
        entry = self.line(element, C.SUBSTITUTED if notes else C.NATIVE, *notes)
        self.made(element, entry, object_id)

    def _line(self, element: dict) -> None:
        self._drawn(element, path_plan(element))

    def _path(self, element: dict) -> None:
        self._drawn(element, path_plan(element))

    def _drawn(self, element: dict, decision: PathPlan) -> None:
        if decision.kind == "nothing":
            self.line(
                element,
                C.IGNORED,
                note("draws-nothing", "It has no outline and no filled area, so nothing shows."),
            )
            return
        if decision.kind == "lines":
            pairs = segments(decision.pieces)
            ids = [oid(element["id"], i) for i in range(len(pairs))]
            for object_id, (start, end) in zip(ids, pairs, strict=True):
                self.requests.append(line_request(object_id, self.slide, start, end))
                self.requests.append(line_style(object_id, element["source"]["styleProperties"]))
            status = C.NATIVE if element["type"] == "line" and len(pairs) == 1 else C.SUBSTITUTED
            entry = self.line(element, status)
            if status == C.SUBSTITUTED:
                entry.notes.append(
                    note("drawn-as-lines", f"Drawn as {len(pairs)} separate straight lines.")
                )
            if len(ids) > 1:
                group = oid(element["id"], "lines")
                self.requests.append(
                    {"groupObjects": {"groupObjectId": group, "childrenObjectIds": ids}}
                )
                entry.objects.append(group)
                self.objects[element["id"]] = [group]
            else:
                self.made(element, entry, *ids)
            return
        drawn = self.prepared.drawn.get(element["id"])
        if drawn is None:
            self.line(element, C.UNSUPPORTED, note("not-drawn", "This drawing could not be made."))
            return
        x, y, width, height = drawn.box
        object_id = oid(element["id"])
        self.requests.append(
            image_request(
                object_id, self.slide, drawn.picture, Frame.from_bounds(x, y, width, height)
            )
        )
        self.pictures[drawn.picture.key] = drawn.picture
        entry = self.line(
            element,
            C.FLATTENED,
            note("drawn-as-picture", "This drawing has no Slides shape, so it is a picture."),
            *drawn.picture.notes,
        )
        self.made(element, entry, object_id)

    def _table(self, element: dict) -> None:
        table = element.get("table") or {}
        rows, columns = table.get("rows", []), table.get("columns", [])
        frame = frame_of(element)
        if frame is None or not rows or not columns:
            self.line(element, C.UNSUPPORTED, note("table-empty", "The table has no cells."))
            return
        object_id = oid(element["id"])
        notes: list[dict] = []
        if frame.rotation:
            notes.append(note("table-not-turned", "Slides tables cannot be turned."))
            frame = Frame(frame.width, frame.height, frame.cx, frame.cy)
        self.requests.append(
            {
                "createTable": {
                    "objectId": object_id,
                    "elementProperties": placed(object_id, self.slide, frame),
                    "rows": len(rows),
                    "columns": len(columns),
                }
            }
        )
        # libmspub 0.1.4 passes on no table borders at all (its TableInfo holds
        # only sizes and spans), so the table is drawn without them, as
        # LibreOffice draws it, rather than with Google's default grey grid.
        # Slides has no "no border": the border is made fully transparent.
        self.requests.append(hidden_borders(object_id))
        for index, column in enumerate(columns):
            width = (column.get("width") or {}).get("points")
            if not width:
                continue
            if width < MIN_COLUMN_WIDTH:
                notes.append(note("column-widened", "A very narrow column was widened."))
            self.requests.append(
                {
                    "updateTableColumnProperties": {
                        "objectId": object_id,
                        "columnIndices": [index],
                        "tableColumnProperties": {
                            "columnWidth": {
                                "magnitude": round(max(width, MIN_COLUMN_WIDTH), 4),
                                "unit": "PT",
                            }
                        },
                        "fields": "columnWidth",
                    }
                }
            )
        for row in rows:
            height = (row.get("height") or {}).get("points") or length_points(
                (row.get("sourceProperties") or {}).get("librevenge:row-height")
            )
            if height:
                self.requests.append(
                    {
                        "updateTableRowProperties": {
                            "objectId": object_id,
                            "rowIndices": [row["index"]],
                            "tableRowProperties": {
                                "minRowHeight": {"magnitude": round(height, 4), "unit": "PT"}
                            },
                            "fields": "minRowHeight",
                        }
                    }
                )
        for row in rows:
            for cell in row.get("cells", []):
                if cell.get("covered"):
                    continue
                location = {"rowIndex": cell["row"], "columnIndex": cell["column"]}
                if cell.get("rowSpan", 1) > 1 or cell.get("columnSpan", 1) > 1:
                    self.requests.append(
                        {
                            "mergeTableCells": {
                                "objectId": object_id,
                                "tableRange": {
                                    "location": location,
                                    "rowSpan": cell.get("rowSpan", 1),
                                    "columnSpan": cell.get("columnSpan", 1),
                                },
                            }
                        }
                    )
                background = colour((cell.get("sourceProperties") or {}).get("fo:background-color"))
                if background:
                    self.requests.append(
                        {
                            "updateTableCellProperties": {
                                "objectId": object_id,
                                "tableRange": {"location": location, "rowSpan": 1, "columnSpan": 1},
                                "tableCellProperties": {
                                    "tableCellBackgroundFill": solid(background)
                                },
                                "fields": "tableCellBackgroundFill",
                            }
                        }
                    )
                text, more = text_requests(
                    object_id, cell.get("paragraphs", []), self.fonts, location
                )
                self.requests += text
                notes += more
        notes.append(
            note(
                "table-borders",
                "The table is drawn without borders: the reader can't see whether the "
                "original had any. If it did, add them in Slides.",
            )
        )
        entry = self.line(element, C.SUBSTITUTED, *_unique(notes))
        self.made(element, entry, object_id)

    def _wrapper(self, element: dict) -> None:
        # Only a container: its contents are drawn in their own right.
        clipped = any(w["code"] == "layer-clip-path" for w in element.get("warnings", []))
        self.line(
            element,
            C.IGNORED,
            note("crop-not-applied", "A crop is not applied: the whole picture is shown.")
            if clipped
            else {},
        )
        self.objects[element["id"]] = []

    def _group(self, element: dict) -> None:
        pass  # made once its contents exist: see group_all

    def _wordart(self, element: dict) -> None:
        """WordArt as a text box over its outlines' extent, sized to fill it."""
        art, box = self.prepared.wordart[element["id"]]
        frame = Frame.from_bounds(*box)
        lines = [line for line in art.text.split("\n") if line]
        object_id = oid(element["id"])
        family = resolve_font(art.font, self.fonts) if art.font else None
        size = wordart_size(art, lines, family, frame)
        text = "\n".join(lines)
        style: dict = {
            "fontSize": {"magnitude": size, "unit": "PT"},
            "bold": art.bold,
            "italic": art.italic,
        }
        fields = ["fontSize", "bold", "italic"]
        if family:
            style["fontFamily"] = family
            fields.append("fontFamily")
        tint = colour(art.colour) or colour(art.line)
        if tint:
            style["foregroundColor"] = {"opaqueColor": rgb(tint)}
            fields.append("foregroundColor")
        whole = {"type": "FIXED_RANGE", "startIndex": 0, "endIndex": utf16(text)}
        self.requests += [
            {
                "createShape": {
                    "objectId": object_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": placed(object_id, self.slide, frame),
                }
            },
            {
                "updateShapeProperties": {
                    "objectId": object_id,
                    "shapeProperties": {
                        "shapeBackgroundFill": {"propertyState": "NOT_RENDERED"},
                        "outline": {"propertyState": "NOT_RENDERED"},
                        "contentAlignment": "MIDDLE",
                    },
                    "fields": "shapeBackgroundFill,outline,contentAlignment",
                }
            },
            {"insertText": {"objectId": object_id, "insertionIndex": 0, "text": text}},
            {
                "updateTextStyle": {
                    "objectId": object_id,
                    "textRange": whole,
                    "style": style,
                    "fields": ",".join(fields),
                }
            },
            {
                "updateParagraphStyle": {
                    "objectId": object_id,
                    "textRange": whole,
                    "style": {"alignment": "CENTER"},
                    "fields": "alignment",
                }
            },
        ]
        entry = self.line(
            element,
            C.SUBSTITUTED,
            note(
                "wordart-text",
                "WordArt was made into ordinary text you can edit. Its shaping, gradient and "
                "effects (such as a reflection) can't be made in Slides.",
            ),
        )
        if art.font and self.fonts.get(art.font, {}).get("status") != FontStatus.AVAILABLE:
            entry.notes.append(note("font-substituted", "A font was replaced; see the fonts."))
        self.made(element, entry, object_id)

    def group_all(self, elements: list[dict]) -> None:
        """Authored groups, innermost first, from the objects their contents became."""
        children: dict[str, list[dict]] = defaultdict(list)
        for element in elements:
            if element.get("parentId"):
                children[element["parentId"]].append(element)
        by_id = {e["id"]: e for e in elements}

        def objects_of(element_id: str) -> list[str]:
            element = by_id.get(element_id)
            if element is None:
                return []
            if element_id in self.objects and element["type"] != "wrapper":
                return self.objects[element_id]
            return [o for child in children[element_id] for o in objects_of(child["id"])]

        def depth(element: dict) -> int:
            level, parent = 0, element.get("parentId")
            while parent and parent in by_id and level < 64:
                level, parent = level + 1, by_id[parent].get("parentId")
            return level

        groups = [
            e for e in elements if e["type"] == "group" and e["id"] not in self.prepared.wordart
        ]
        for group in sorted(groups, key=depth, reverse=True):
            members = [o for c in children[group["id"]] for o in objects_of(c["id"])]
            kinds = {by_id[c["id"]]["type"] for c in children[group["id"]]}
            entry = self.line(group, C.NATIVE)
            if len(members) >= 2 and not kinds & UNGROUPABLE:
                group_id = oid(group["id"])
                self.requests.append(
                    {"groupObjects": {"groupObjectId": group_id, "childrenObjectIds": members}}
                )
                self.made(group, entry, group_id)
            else:
                entry.status = C.SUBSTITUTED
                entry.notes.append(
                    note(
                        "group-not-kept",
                        "Its contents are kept, but not as one group (a group needs two or "
                        "more items, and cannot hold a table).",
                    )
                )
                self.objects[group["id"]] = members

    def _unknown(self, element: dict) -> None:
        self.line(
            element,
            C.UNSUPPORTED,
            note("unknown-element", "The reader could not tell what this is, so it is left out."),
        )


# Parser warnings the renderer has acted on, so they are not repeated.
SETTLED = {
    "wrapper-not-a-group",
    "probable-border-art",
    "rotation-from-outline",
    "table-row-heights-unknown",
    "path-flattened",
}


def _families(paragraphs: list[dict]) -> set[str]:
    return {
        r["style"]["fontFamily"]
        for p in paragraphs
        for r in p.get("runs", [])
        if r["style"].get("fontFamily")
    }


def _table_families(element: dict) -> set[str]:
    return {
        f
        for row in (element.get("table") or {}).get("rows", [])
        for cell in row.get("cells", [])
        for f in _families(cell.get("paragraphs", []))
    }


# ------------------------------------------------------------------ the document


def probable_master(pages: list[dict]) -> set[str]:
    """Elements drawn identically on every page: probably the master page's.

    libmspub paints master content into each page with no marker, so it is
    only reported, never removed (readiness §7.5).
    """
    if len(pages) < 2:
        return set()

    def signature(element: dict) -> tuple | None:
        bounds = element.get("bounds")
        if not bounds:
            return None
        return (
            element["type"],
            tuple(round(bounds[k], 1) for k in ("x", "y", "width", "height")),
            (element.get("image") or {}).get("assetId"),
        )

    per_page = [
        {signature(e): e["id"] for e in page.get("elements", []) if signature(e)} for page in pages
    ]
    shared = set.intersection(*(set(p) for p in per_page))
    return {p[s] for p in per_page for s in shared}


def plan(document: dict, prepared: Prepared, *, title: str, delete: Iterable[str] = ()) -> Plan:
    pages = [p for p in document.get("pages", []) if p.get("kind", "page") == "page"]
    if not pages:
        raise ValueError("the document has no pages")
    warnings: list[dict] = []
    first = pages[0]
    width, height = first.get("width"), first.get("height")
    if not width or not height:
        width, height = 595.275591, 841.889764  # A4 portrait
        warnings.append(
            note("page-size-unknown", "The page size was not recorded, so A4 portrait is used.")
        )
    if any(
        abs((p.get("width") or width) - width) > 0.5
        or abs((p.get("height") or height) - height) > 0.5
        for p in pages
    ):
        warnings.append(
            note(
                "page-sizes-differ",
                "Pages differ in size. Google Slides has one size for every slide, so the "
                "first page's is used.",
            )
        )
    masters = [p for p in document.get("pages", []) if p.get("kind") == "master"]
    if masters:
        warnings.append(
            note(
                "master-pages",
                "Master page content already appears on each page it applies to.",
            )
        )
    create = {"title": title, "pageSize": size(width, height)}
    slides = [oid("page", f"{i + 1:04d}") for i in range(len(pages))]
    setup: list[dict] = [
        {
            "createSlide": {
                "objectId": slide,
                "insertionIndex": index,
                "slideLayoutReference": {"predefinedLayout": "BLANK"},
            }
        }
        for index, slide in enumerate(slides)
    ]
    setup += [{"deleteObject": {"objectId": existing}} for existing in delete]
    for page, slide in zip(pages, slides, strict=True):
        background = page.get("sourceProperties") or {}
        tint = colour(background.get("draw:fill-color"))
        if background.get("draw:fill") == "solid" and tint:
            setup.append(
                {
                    "updatePageProperties": {
                        "objectId": slide,
                        "pageProperties": {
                            "pageBackgroundFill": solid(
                                tint, opacity(background.get("draw:opacity"))
                            )
                        },
                        "fields": "pageBackgroundFill",
                    }
                }
            )

    fonts: dict[str, dict] = {}
    requests: list[list[dict]] = []
    lines: list[Line] = []
    pictures: dict[str, Picture] = {}
    for page, slide in zip(pages, slides, strict=True):
        builder = PageBuilder(page, slide, prepared, fonts)
        builder.build()
        requests.append(builder.requests)
        pictures.update(builder.pictures)
        lines += sorted(builder.lines.values(), key=lambda line: line.element_id)
    master = probable_master(pages)
    for entry in lines:
        if entry.element_id in master:
            entry.notes.append(
                note(
                    "probable-master",
                    "This appears identically on every page, so it probably comes from the "
                    "master page.",
                )
            )
    families = set(fonts)
    for page in pages:
        for element in page.get("elements", []):
            families |= _table_families(element)
    report = {
        "pageSize": {"width": width, "height": height, "unit": "pt"},
        "pages": len(pages),
        "elements": [line.as_dict() for line in lines],
        "statusCounts": dict(Counter(str(line.status) for line in lines)),
        "fonts": catalogue(families),
        "warnings": warnings
        + prepared.notes
        + [
            note(
                "text-insets",
                "Google Slides uses its own space inside text boxes, which may differ "
                "slightly from Publisher's, so text can wrap a little differently.",
            )
        ],
        "basis": BASIS,
    }
    return Plan(create, setup, requests, pictures, slides, report)


# ------------------------------------------------------------------ checking


KNOWN = {
    "createSlide",
    "deleteObject",
    "updatePageProperties",
    "createShape",
    "updateShapeProperties",
    "insertText",
    "updateTextStyle",
    "updateParagraphStyle",
    "createImage",
    "createLine",
    "updateLineProperties",
    "createTable",
    "updateTableColumnProperties",
    "updateTableRowProperties",
    "updateTableCellProperties",
    "updateTableBorderProperties",
    "mergeTableCells",
    "groupObjects",
}
CREATES = {
    "createSlide": "objectId",
    "createShape": "objectId",
    "createImage": "objectId",
    "createLine": "objectId",
    "createTable": "objectId",
    "groupObjects": "groupObjectId",
}


def check(plan_: Plan, *, existing: Iterable[str] = (), bound: bool = False) -> list[str]:
    """Problems Google would refuse the plan for, found before anything is sent.

    Each request has one known kind; every ID made is valid and new; nothing
    is used before it is made; every text range lies inside the text; and,
    once bound, every picture has a real link.
    """
    problems: list[str] = []
    made: set[str] = set(existing)
    tables: dict[str, tuple[int, int]] = {}
    lengths: dict[tuple, int] = {}
    everything = plan_.setup + [r for page in plan_.pages for r in page]
    for number, request in enumerate(everything):
        if len(request) != 1 or next(iter(request)) not in KNOWN:
            problems.append(f"#{number}: not one known request: {sorted(request)}")
            continue
        kind, body = next(iter(request.items()))
        if kind in CREATES:
            new = body[CREATES[kind]]
            if not OBJECT_ID.match(new):
                problems.append(f"#{number}: invalid ID {new!r}")
            if new in made:
                problems.append(f"#{number}: {new} made twice")
            if kind == "groupObjects":
                for child in body["childrenObjectIds"]:
                    if child not in made:
                        problems.append(f"#{number}: groups {child} before it exists")
                if len(body["childrenObjectIds"]) < 2:
                    problems.append(f"#{number}: a group of fewer than two")
            made.add(new)
            if kind == "createTable":
                tables[new] = (body["rows"], body["columns"])
            page = body.get("elementProperties", {}).get("pageObjectId")
            if page and page not in made:
                problems.append(f"#{number}: placed on {page} before it exists")
            if kind == "createImage" and bound and body["url"].startswith(PICTURE):
                problems.append(f"#{number}: picture {body['url']} has no link")
            continue
        target = body.get("objectId")
        if target and target not in made:
            problems.append(f"#{number}: {kind} on {target} before it exists")
        if kind == "deleteObject":
            made.discard(target)
            continue
        cell = body.get("cellLocation")
        key = (target, cell["rowIndex"], cell["columnIndex"]) if cell else (target,)
        if cell and target in tables:
            rows, columns = tables[target]
            if not (0 <= cell["rowIndex"] < rows and 0 <= cell["columnIndex"] < columns):
                problems.append(f"#{number}: cell {cell} outside the table")
        if kind == "insertText":
            stray = {ch for ch in body["text"] if ch in DROPPED and ch != "\n"}
            if stray:
                problems.append(f"#{number}: text holds characters Slides drops: {sorted(stray)}")
            if body["insertionIndex"] > lengths.get(key, 0):
                problems.append(f"#{number}: text inserted past the end")
            lengths[key] = lengths.get(key, 0) + utf16(body["text"])
        elif kind in {"updateTextStyle", "updateParagraphStyle"}:
            text_range = body["textRange"]
            start, end = text_range["startIndex"], text_range["endIndex"]
            if not 0 <= start < end <= lengths.get(key, 0):
                problems.append(f"#{number}: range {start}-{end} outside {lengths.get(key, 0)}")
            if not body.get("fields"):
                problems.append(f"#{number}: no fields")
    return problems
