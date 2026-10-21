"""Plays one PowerPoint slide's animation to a video (prototype).

Google Slides cannot take PowerPoint animations, and the Slides API cannot
create them. A slide that is really a timed scene (pictures arriving, leaving
and moving, with sound cues) can only be kept by recording it. PowerPoint
itself cannot run on the hosted service, and LibreOffice cannot play
animations to video, so this plays the animation itself: it reads the slide's
timing tree, draws each moment with Pillow, mixes the sound cues, and has
ffmpeg encode an MP4.

What it plays: appear/disappear, fade, wipe, wheel, fly in, motion paths,
grow/shrink, spin and transparency, started in the order and at the times the
slide states, plus sound cues. Anything else is played as a fade and counted
in `notes`. What it draws: pictures (cropped, flipped, turned), groups (nested,
with their own coordinate spaces) and text boxes in a stand-in font. It is
approximate, and says where.

The file is untrusted: sizes and counts are bounded, and nothing is executed.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import re
import shutil
import subprocess  # nosec B404 -- fixed argv, no shell, ffmpeg only
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Type annotation only; XML parsing always uses defusedxml.
from xml.etree.ElementTree import Element  # nosec B405

from defusedxml import ElementTree as SafeET
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning

logger = logging.getLogger(__name__)

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
}
P = f"{{{NS['p']}}}"
A = f"{{{NS['a']}}}"
R = f"{{{NS['r']}}}"
EMU_PER_PT = 12700
MAX_SECONDS = 180
# A click-to-reveal slide has a few effects; a timed scene has dozens.
HEAVY_EFFECTS = 20
MAX_PIXELS = 40_000_000  # one picture, decoded
MAX_SPRITE_PIXELS = 60_000_000
MAX_MEDIA_BYTES = 80 * 1024 * 1024


# ---------------------------------------------------------------- the slide


@dataclass
class Node:
    """One shape, picture or group, in its own coordinate space (EMU)."""

    kind: str  # pic, grp, sp
    id: str
    name: str
    x: float
    y: float
    w: float
    h: float
    rot: float = 0.0  # degrees clockwise
    flip_h: bool = False
    flip_v: bool = False
    children: list[Node] = field(default_factory=list)
    child_box: tuple[float, float, float, float] | None = None  # chOff, chExt
    blip: str | None = None  # the media part a picture shows
    crop: tuple[float, float, float, float] = (0, 0, 0, 0)  # l, t, r, b as fractions
    text: list[dict] = field(default_factory=list)  # paragraphs: {text, size, bold, colour, align}
    audio: str | None = None  # the media part a sound picture plays
    trim: tuple[float, float] | None = None  # sound trim, ms
    outline: tuple[float, str] | None = None  # picture border: width EMU, RRGGBB


@dataclass
class Scene:
    width_emu: float
    height_emu: float
    nodes: list[Node]
    by_id: dict[str, Node]
    media: dict[str, bytes]  # part -> bytes, only what is used
    background: tuple[int, int, int] = (255, 255, 255)


def _num(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    folder, _, base = part.rpartition("/")
    name = f"{folder}/_rels/{base}.rels"
    if name not in archive.namelist():
        return {}
    found = {}
    for rel in SafeET.fromstring(archive.read(name)):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External" or target == "NULL":
            continue
        resolved = _join(folder, target)
        found[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], resolved)
    return found


def _join(folder: str, target: str) -> str:
    parts = [] if target.startswith("/") else folder.split("/")
    for piece in target.lstrip("/").split("/"):
        if piece == "..":
            if parts:
                parts.pop()
        elif piece and piece != ".":
            parts.append(piece)
    return "/".join(parts)


def slide_parts(archive: zipfile.ZipFile) -> list[str]:
    """The slide parts in the order the deck shows them."""
    presentation = SafeET.fromstring(archive.read("ppt/presentation.xml"))
    rels = _rels(archive, "ppt/presentation.xml")
    return [
        rels[s.get(R + "id", "")][1]
        for s in presentation.findall("p:sldIdLst/p:sldId", NS)
        if s.get(R + "id", "") in rels
    ]


def slide_part(archive: zipfile.ZipFile, number: int) -> str:
    order = slide_parts(archive)
    if not 1 <= number <= len(order):
        raise ValueError(f"The deck has {len(order)} slides; there is no slide {number}.")
    return order[number - 1]


def _xfrm(node: Element) -> Element | None:
    for path in ("p:spPr/a:xfrm", "p:grpSpPr/a:xfrm"):
        found = node.find(path, NS)
        if found is not None:
            return found
    return None


def _read_node(
    el: Element, rels: dict, media: dict, archive: zipfile.ZipFile, load: bool = True
) -> Node | None:
    tag = el.tag.split("}")[1]
    if tag not in ("sp", "pic", "grpSp"):
        return None
    props = el.find(".//p:cNvPr", NS)
    xf = _xfrm(el)
    if props is None or xf is None:
        return None
    off, ext = xf.find("a:off", NS), xf.find("a:ext", NS)
    if off is None or ext is None:
        return None
    node = Node(
        kind={"sp": "sp", "pic": "pic", "grpSp": "grp"}[tag],
        id=props.get("id", ""),
        name=props.get("name", ""),
        x=_num(off.get("x")),
        y=_num(off.get("y")),
        w=_num(ext.get("cx")),
        h=_num(ext.get("cy")),
        rot=_num(xf.get("rot")) / 60000,
        flip_h=xf.get("flipH") == "1",
        flip_v=xf.get("flipV") == "1",
    )
    if tag == "grpSp":
        co, ce = xf.find("a:chOff", NS), xf.find("a:chExt", NS)
        if co is not None and ce is not None:
            node.child_box = (
                _num(co.get("x")),
                _num(co.get("y")),
                _num(ce.get("cx")),
                _num(ce.get("cy")),
            )
        for child in el:
            sub = _read_node(child, rels, media, archive, load)
            if sub:
                node.children.append(sub)
    elif tag == "pic":
        blip = el.find(".//a:blip", NS)
        target = rels.get(blip.get(R + "embed", ""), ("", ""))[1] if blip is not None else ""
        if target and target in archive.namelist():
            if archive.getinfo(target).file_size <= MAX_MEDIA_BYTES:
                node.blip = target
                if load:
                    media.setdefault(target, archive.read(target))
        line = el.find("p:spPr/a:ln", NS)
        if line is not None and line.find("a:noFill", NS) is None:
            colour = line.find("a:solidFill/a:srgbClr", NS)
            node.outline = (
                _num(line.get("w"), 9525),
                colour.get("val", "000000") if colour is not None else "000000",
            )
        src = el.find(".//a:srcRect", NS)
        if src is not None:
            node.crop = tuple(_num(src.get(k)) / 100000 for k in ("l", "t", "r", "b"))  # type: ignore[assignment]
        sound = el.find(".//p14:media", NS)
        if sound is not None:
            target = rels.get(sound.get(R + "embed", ""), ("", ""))[1]
            if (
                target
                and target in archive.namelist()
                and archive.getinfo(target).file_size <= MAX_MEDIA_BYTES
            ):
                node.audio = target
                if load:
                    media.setdefault(target, archive.read(target))
            trim = el.find(".//p14:trim", NS)
            if trim is not None:
                node.trim = (_num(trim.get("st")), _num(trim.get("end")))
    else:
        for paragraph in el.findall(".//a:p", NS):
            runs = paragraph.findall("a:r", NS)
            text = "".join((r.findtext("a:t", default="", namespaces=NS) or "") for r in runs)
            if not text.strip():
                continue
            first = runs[0].find("a:rPr", NS)
            text_colour: str | None = None
            if first is not None:
                swatch = first.find("a:solidFill/a:srgbClr", NS)
                text_colour = swatch.get("val") if swatch is not None else None
            paragraph_props = paragraph.find("a:pPr", NS)
            align = (paragraph_props.get("algn") if paragraph_props is not None else None) or "l"
            node.text.append(
                {
                    "text": text,
                    "size": _num(first.get("sz") if first is not None else None, 1800) / 100,
                    "bold": first is not None and first.get("b") == "1",
                    "colour": text_colour or "000000",
                    "align": align,
                }
            )
    return node


def read_scene(archive: zipfile.ZipFile, part: str, load_media: bool = True) -> Scene:
    """The slide's shapes. `load_media=False` leaves out the pictures' and clips' bytes."""
    presentation = SafeET.fromstring(archive.read("ppt/presentation.xml"))
    size = presentation.find("p:sldSz", NS)
    root = SafeET.fromstring(archive.read(part))
    rels = _rels(archive, part)
    media: dict[str, bytes] = {}
    nodes = []
    tree = root.find("p:cSld/p:spTree", NS)
    for child in tree if tree is not None else []:
        node = _read_node(child, rels, media, archive, load_media)
        if node:
            nodes.append(node)
    return Scene(
        _num(size.get("cx"), 12192000) if size is not None else 12192000,
        _num(size.get("cy"), 6858000) if size is not None else 6858000,
        nodes,
        {n.id: n for n in nodes},
        media,
    )


# ---------------------------------------------------------------- the timeline


@dataclass
class Effect:
    """One thing that happens to one shape, with absolute times in ms."""

    shape: str
    kind: str  # visibility, reveal, position, motion, scale, rotate, opacity
    start: float
    dur: float
    hold: bool = True
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Cue:
    shape: str
    start: float
    dur: float
    offset: float = 0.0  # playFrom(seconds)


@dataclass
class Timeline:
    effects: list[Effect]
    cues: list[Cue]
    entrance: set[str]  # shapes that start hidden
    end_ms: float
    notes: list[str]
    volumes: dict[str, float] = field(default_factory=dict)  # sound picture -> 0..1


def _delay(ctn: Element) -> float:
    cond = ctn.find("p:stCondLst/p:cond", NS)
    value = cond.get("delay") if cond is not None else None
    return float(value) if value and value.lstrip("-").isdigit() else 0.0


def _dur(ctn: Element | None) -> float:
    value = ctn.get("dur") if ctn is not None else None
    return float(value) if value and value.isdigit() else 0.0


def parse_timeline(root: Element) -> Timeline:
    timeline = Timeline([], [], set(), 0.0, [])
    timing = root.find("p:timing", NS)
    if timing is None:
        return timeline
    main = next((c for c in timing.iter(P + "cTn") if c.get("nodeType") == "mainSeq"), None)
    if main is None:
        return timeline
    for audio in timing.iter(P + "audio"):
        media = audio.find("p:cMediaNode", NS)
        spot = media.find(".//p:spTgt", NS) if media is not None else None
        if media is not None and spot is not None and media.get("vol"):
            timeline.volumes[spot.get("spid", "")] = _num(media.get("vol"), 100000) / 100000
    running = 0.0
    for group in main.findall("p:childTnLst/p:par/p:cTn", NS):
        # A click starts the next group when the last has played out.
        before = timeline.end_ms
        _walk(group, running if before == 0 else before, timeline, top=True)
        running = timeline.end_ms
    return timeline


def _walk(ctn: Element, base: float, timeline: Timeline, top: bool = False) -> None:
    start = base if top else base + _delay(ctn)
    if ctn.get("presetClass"):
        _effect(ctn, start, timeline)
        return
    for sub in ctn.findall("p:childTnLst/p:par/p:cTn", NS):
        _walk(sub, start, timeline)
    for sub in ctn.findall("p:childTnLst/p:seq/p:cTn", NS):
        _walk(sub, start, timeline)


def _target(behaviour: Element) -> str | None:
    spid = behaviour.find("p:cBhvr/p:tgtEl/p:spTgt", NS)
    return spid.get("spid") if spid is not None else None


def _effect(ctn: Element, start: float, timeline: Timeline) -> None:
    klass = ctn.get("presetClass", "")
    hold = ctn.get("fill") == "hold"
    accel, decel = _num(ctn.get("accel")) / 100000, _num(ctn.get("decel")) / 100000
    children = ctn.find("p:childTnLst", NS)
    for behaviour in children if children is not None else []:
        tag = behaviour.tag.split("}")[1]
        if tag == "audio":
            continue  # its volume is read for the whole slide, above
        inner = behaviour.find("p:cBhvr/p:cTn", NS)
        began = start + _delay(inner) if inner is not None else start
        dur = _dur(inner)
        target = _target(behaviour)
        timeline.end_ms = max(timeline.end_ms, began + dur)
        if target is None:
            continue
        if klass == "entr":
            timeline.entrance.add(target)
        if tag == "cmd":
            if (behaviour.get("cmd") or "").startswith("playFrom"):
                match = re.search(r"playFrom\(([\d.]+)\)", behaviour.get("cmd", ""))
                timeline.cues.append(
                    Cue(target, began, dur, float(match.group(1)) if match else 0.0)
                )
            continue
        if tag == "set":
            attr = behaviour.findtext("p:cBhvr/p:attrNameLst/p:attrName", default="", namespaces=NS)
            value = behaviour.find("p:to/p:strVal", NS)
            val = value.get("val", "") if value is not None else ""
            if attr == "style.visibility":
                timeline.effects.append(
                    Effect(target, "visibility", began, 0, True, {"visible": val == "visible"})
                )
            elif attr == "style.opacity":
                timeline.effects.append(
                    Effect(target, "opacity", began, dur, hold, {"value": _num(val, 1)})
                )
            continue
        if tag == "animEffect":
            filt = behaviour.get("filter", "")
            if filt == "image":
                continue  # an opacity look, set by its twin `set`
            timeline.effects.append(
                Effect(
                    target,
                    "reveal",
                    began,
                    dur,
                    hold,
                    {"filter": filt, "out": behaviour.get("transition") == "out"},
                )
            )
            continue
        if tag == "anim":
            attrs = [
                a.text or "" for a in behaviour.findall("p:cBhvr/p:attrNameLst/p:attrName", NS)
            ]
            frames = []
            for tav in behaviour.findall("p:tavLst/p:tav", NS):
                text_value = tav.find("p:val/p:strVal", NS)
                number_value = tav.find("p:val/p:fltVal", NS)
                frames.append(
                    (
                        float(tav.get("tm", "0")) / 100000,
                        text_value.get("val", "")
                        if text_value is not None
                        else number_value.get("val", "0")
                        if number_value is not None
                        else "0",
                    )
                )
            for attr in attrs:
                if attr in ("ppt_x", "ppt_y", "ppt_w", "ppt_h") and frames:
                    timeline.effects.append(
                        Effect(
                            target,
                            "position",
                            began,
                            dur,
                            hold,
                            {"attr": attr, "frames": frames, "accel": accel, "decel": decel},
                        )
                    )
            continue
        if tag == "animMotion":
            timeline.effects.append(
                Effect(
                    target,
                    "motion",
                    began,
                    dur,
                    hold,
                    {"path": _path(behaviour.get("path", "")), "accel": accel, "decel": decel},
                )
            )
            continue
        if tag == "animScale":
            by = behaviour.find("p:by", NS)
            if by is not None:
                timeline.effects.append(
                    Effect(
                        target,
                        "scale",
                        began,
                        dur,
                        hold,
                        {
                            "x": _num(by.get("x"), 100000) / 100000,
                            "y": _num(by.get("y"), 100000) / 100000,
                            "accel": accel,
                            "decel": decel,
                        },
                    )
                )
            continue
        if tag == "animRot":
            timeline.effects.append(
                Effect(
                    target,
                    "rotate",
                    began,
                    dur,
                    hold,
                    {"by": _num(behaviour.get("by")) / 60000, "accel": accel, "decel": decel},
                )
            )
            continue
        timeline.notes.append(f"{tag} was not played")


def _path(text: str) -> list[tuple[float, float]]:
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)]
    return [(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)]


# ---------------------------------------------------------------- the maths


def ease(p: float, accel: float, decel: float) -> float:
    """Progress with a speed-up over the first `accel` and a slow-down over the last `decel`."""
    p = min(1.0, max(0.0, p))
    if accel + decel <= 0:
        return p
    top = 1 / (1 - (accel + decel) / 2)
    if accel and p < accel:
        return 0.5 * top * p * p / accel
    if decel and p > 1 - decel:
        q = 1 - p
        return 1 - 0.5 * top * q * q / decel
    return 0.5 * top * accel + top * (p - accel)


def along(points: list[tuple[float, float]], s: float) -> tuple[float, float]:
    """The point a fraction `s` of the way along a polyline, by length."""
    if not points:
        return 0.0, 0.0
    if len(points) == 1:
        return points[0]
    lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lengths)
    if total == 0:
        return points[0]
    want, walked = s * total, 0.0
    for i, length in enumerate(lengths):
        if walked + length >= want or i == len(lengths) - 1:
            f = 0.0 if length == 0 else min(1.0, (want - walked) / length)
            (x1, y1), (x2, y2) = points[i], points[i + 1]
            return x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
        walked += length
    return points[-1]


TOKEN = re.compile(r"\s*(#[a-z_]+|\d+\.?\d*(?:[eE][-+]?\d+)?|[()+\-*/])")


def evaluate(expression: str, variables: dict[str, float]) -> float:
    """A PowerPoint animation value such as `1+#ppt_w/2`, without ever using eval."""
    tokens, pos = [], 0
    text = expression.strip()
    while pos < len(text):
        found = TOKEN.match(text, pos)
        if not found:
            raise ValueError("unexpected character in animation value")
        tokens.append(found.group(1))
        pos = found.end()
    index = 0

    def peek() -> str | None:
        return tokens[index] if index < len(tokens) else None

    def take() -> str:
        nonlocal index
        index += 1
        return tokens[index - 1]

    def atom() -> float:
        piece = take()
        if piece == "(":
            value = expr()
            take()
            return value
        if piece == "-":
            return -atom()
        if piece.startswith("#"):
            return variables.get(piece[1:], 0.0)
        return float(piece)

    def term() -> float:
        value = atom()
        while peek() in ("*", "/"):
            op = take()
            right = atom()
            value = value * right if op == "*" else (value / right if right else 0.0)
        return value

    def expr() -> float:
        value = term()
        while peek() in ("+", "-"):
            op = take()
            right = term()
            value = value + right if op == "+" else value - right
        return value

    return expr()


# ---------------------------------------------------------------- drawing


@dataclass
class Sprite:
    image: Image.Image  # RGBA, at output scale
    left: float  # px, may be off the canvas
    top: float
    cx: float  # centre, px
    cy: float


def _font(size_px: float, bold: bool) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=max(6, int(size_px)))
    except TypeError:  # an older Pillow has no sized default font
        return ImageFont.load_default()


def _bounds(node: Node, m: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """The slide-space box (EMU) a node occupies, turned as it is turned."""
    sx, sy, tx, ty = m
    x0, y0 = tx + sx * node.x, ty + sy * node.y
    w, h = sx * node.w, sy * node.h
    if node.kind == "grp" and node.child_box:
        co = node.child_box
        kx, ky = (node.w / co[2] if co[2] else 1.0), (node.h / co[3] if co[3] else 1.0)
        inner = (sx * kx, sy * ky, tx + sx * (node.x - co[0] * kx), ty + sy * (node.y - co[1] * ky))
        boxes = [_bounds(c, inner) for c in node.children]
        if boxes:
            x0 = min(b[0] for b in boxes)
            y0 = min(b[1] for b in boxes)
            w = max(b[0] + b[2] for b in boxes) - x0
            h = max(b[1] + b[3] for b in boxes) - y0
    if node.rot % 360:
        a = math.radians(node.rot)
        cx, cy = x0 + w / 2, y0 + h / 2
        nw = abs(w * math.cos(a)) + abs(h * math.sin(a))
        nh = abs(w * math.sin(a)) + abs(h * math.cos(a))
        return cx - nw / 2, cy - nh / 2, nw, nh
    return x0, y0, w, h


def _draw(
    node: Node,
    m: tuple[float, float, float, float],
    layer: Image.Image,
    origin: tuple[float, float],
    px: float,
    media: dict,
) -> None:
    """Draws `node` onto `layer`, whose top left is `origin` (EMU) at `px` pixels per EMU."""
    sx, sy, tx, ty = m
    x0, y0 = tx + sx * node.x, ty + sy * node.y
    w, h = sx * node.w, sy * node.h
    if node.kind == "grp" and node.child_box:
        co = node.child_box
        kx, ky = (node.w / co[2] if co[2] else 1.0), (node.h / co[3] if co[3] else 1.0)
        inner = (sx * kx, sy * ky, tx + sx * (node.x - co[0] * kx), ty + sy * (node.y - co[1] * ky))
        for child in node.children:
            _draw(child, inner, layer, origin, px, media)
        return
    pw, ph = max(1, round(w * px)), max(1, round(h * px))
    if pw * ph > MAX_SPRITE_PIXELS:
        return
    piece: Image.Image | None = None
    if node.kind == "pic" and node.blip and node.blip in media:
        piece = _picture(node, media[node.blip], pw, ph)
        if piece is not None and node.outline and re.fullmatch(r"[0-9A-Fa-f]{6}", node.outline[1]):
            width = max(1, round(node.outline[0] * px))
            ImageDraw.Draw(piece).rectangle(
                (0, 0, pw - 1, ph - 1), outline="#" + node.outline[1], width=width
            )
    elif node.kind == "sp" and node.text:
        piece = _text(node, pw, ph, px * EMU_PER_PT)
    if piece is None:
        return
    if node.flip_h:
        piece = ImageOps.mirror(piece)
    if node.flip_v:
        piece = ImageOps.flip(piece)
    cx, cy = (x0 + w / 2 - origin[0]) * px, (y0 + h / 2 - origin[1]) * px
    if node.rot % 360:
        piece = piece.rotate(-node.rot, resample=Image.Resampling.BICUBIC, expand=True)
    left, top = round(cx - piece.width / 2), round(cy - piece.height / 2)
    _paste(layer, piece, left, top)


def _paste(layer: Image.Image, piece: Image.Image, left: int, top: int) -> None:
    box = (
        max(0, left),
        max(0, top),
        min(layer.width, left + piece.width),
        min(layer.height, top + piece.height),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    cropped = piece.crop((box[0] - left, box[1] - top, box[2] - left, box[3] - top))
    base = layer.crop(box)
    layer.paste(Image.alpha_composite(base, cropped), box[:2])


def _picture(node: Node, data: bytes, pw: int, ph: int) -> Image.Image | None:
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        opened = Image.open(io.BytesIO(data))
        opened.load()
    except Exception:  # noqa: BLE001  # an unreadable picture is skipped, not fatal
        return None
    source: Image.Image = opened.convert("RGBA")
    left_c, top_c, right_c, bottom_c = node.crop
    sw, sh = source.size
    box = (
        round(sw * left_c),
        round(sh * top_c),
        round(sw * (1 - right_c)),
        round(sh * (1 - bottom_c)),
    )
    if box[2] - box[0] > 0 and box[3] - box[1] > 0:
        if min(box[:2]) < 0 or box[2] > sw or box[3] > sh:
            padded = Image.new(
                "RGBA", (max(sw, box[2]) - min(0, box[0]), max(sh, box[3]) - min(0, box[1]))
            )
            padded.paste(source, (-min(0, box[0]), -min(0, box[1])))
            shift = (-min(0, box[0]), -min(0, box[1]))
            source = padded.crop(
                (box[0] + shift[0], box[1] + shift[1], box[2] + shift[0], box[3] + shift[1])
            )
        else:
            source = source.crop(box)
    return source.resize((pw, ph), Image.Resampling.BICUBIC)


def _text(node: Node, pw: int, ph: int, px_per_pt: float) -> Image.Image:
    image = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    lines = []
    for p in node.text:
        font = _font(p["size"] * px_per_pt, p["bold"])
        box = draw.textbbox((0, 0), p["text"], font=font)
        lines.append((p, font, box[2] - box[0], box[3] - box[1]))
    total = sum(h for *_, h in lines) * 1.2
    y = max(0, (ph - total) / 2)
    for p, font, width, height in lines:
        x = {"ctr": (pw - width) / 2, "r": pw - width}.get(p["align"], 0)
        colour = "#" + p["colour"] if re.fullmatch(r"[0-9A-Fa-f]{6}", p["colour"]) else "#000000"
        draw.text((x, y), p["text"], font=font, fill=colour, stroke_width=1, stroke_fill="white")
        y += height * 1.2
    return image


def build_sprite(node: Node, scale: float, media: dict) -> Sprite | None:
    """A node drawn once at output size: its pixels, and where its centre is."""
    box = _bounds(node, (1.0, 1.0, 0.0, 0.0))
    px = scale / EMU_PER_PT
    width, height = max(1, math.ceil(box[2] * px)), max(1, math.ceil(box[3] * px))
    if width * height > MAX_SPRITE_PIXELS:
        return None
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    _draw(node, (1.0, 1.0, 0.0, 0.0), layer, (box[0], box[1]), px, media)
    return Sprite(
        layer, box[0] * px, box[1] * px, (box[0] + box[2] / 2) * px, (box[1] + box[3] / 2) * px
    )


# ---------------------------------------------------------------- the player


@dataclass
class State:
    visible: bool = True
    alpha: float = 1.0
    dx: float = 0.0  # fractions of the slide
    dy: float = 0.0
    scale: float = 1.0
    scale_y: float = 1.0
    rot: float = 0.0
    reveal: tuple[str, float] | None = None  # filter, progress
    place: tuple[float | None, float | None] = (None, None)  # absolute centre override

    def key(self) -> tuple:
        return (
            self.visible,
            round(self.alpha, 3),
            round(self.dx, 4),
            round(self.dy, 4),
            round(self.scale, 3),
            round(self.scale_y, 3),
            round(self.rot, 2),
            self.reveal and (self.reveal[0], round(self.reveal[1], 3)),
            self.place,
        )


class Player:
    def __init__(self, scene: Scene, timeline: Timeline, width: int = 1280) -> None:
        self.scene, self.timeline = scene, timeline
        self.width = width
        self.scale = width / (scene.width_emu / EMU_PER_PT)  # px per pt
        self.height = round(scene.height_emu / EMU_PER_PT * self.scale)
        self.height += self.height % 2
        self.width += self.width % 2
        self.sprites: dict[str, Sprite | None] = {}
        for node in scene.nodes:
            self.sprites[node.id] = build_sprite(node, self.scale, scene.media)
        self.by_shape: dict[str, list[Effect]] = {}
        for effect in timeline.effects:
            if effect.shape in scene.by_id:
                self.by_shape.setdefault(effect.shape, []).append(effect)
            else:
                timeline.notes.append(
                    f"an effect on shape {effect.shape}, which is inside a group, was not played"
                )
        self.timeline.notes = sorted(set(self.timeline.notes))

    def state(self, node: Node, t: float) -> State:
        effects = self.by_shape.get(node.id, [])
        s = State(visible=node.id not in self.timeline.entrance)
        base_cx = (node.x + node.w / 2) / self.scene.width_emu
        base_cy = (node.y + node.h / 2) / self.scene.height_emu
        toggles = sorted(
            (e for e in effects if e.kind == "visibility" and e.start <= t), key=lambda e: e.start
        )
        if toggles:
            s.visible = toggles[-1].data["visible"]
        for e in effects:
            if e.kind in ("visibility",) or t < e.start:
                continue
            raw = (t - e.start) / e.dur if e.dur > 0 else 1.0
            done = raw >= 1
            if (
                done
                and not e.hold
                and e.kind in ("motion", "scale", "rotate", "position", "opacity")
            ):
                continue
            p = min(1.0, raw)
            if e.kind == "opacity":
                s.alpha *= e.data["value"]
            elif e.kind == "reveal":
                filt, out = e.data["filter"], e.data["out"]
                if done and out:
                    s.visible = False if not toggles else s.visible
                    continue
                if done:
                    continue
                if filt == "fade":
                    s.alpha *= (1 - p) if out else p
                else:
                    s.reveal = (filt, (1 - p) if out else p)
            elif e.kind == "motion":
                x, y = along(e.data["path"], ease(p, e.data["accel"], e.data["decel"]))
                s.dx += x
                s.dy += y
            elif e.kind == "scale":
                q = ease(p, e.data["accel"], e.data["decel"])
                s.scale *= 1 + (e.data["x"] - 1) * q
                s.scale_y *= 1 + (e.data["y"] - 1) * q
            elif e.kind == "rotate":
                s.rot += e.data["by"] * ease(p, e.data["accel"], e.data["decel"])
            elif e.kind == "position":
                frames = e.data["frames"]
                variables = {
                    "ppt_x": base_cx,
                    "ppt_y": base_cy,
                    "ppt_w": node.w / self.scene.width_emu,
                    "ppt_h": node.h / self.scene.height_emu,
                }
                q = ease(p, e.data["accel"], e.data["decel"])
                value = self._keyframe(frames, q, variables)
                if e.data["attr"] == "ppt_x":
                    s.place = (value, s.place[1])
                elif e.data["attr"] == "ppt_y":
                    s.place = (s.place[0], value)
        return s

    @staticmethod
    def _keyframe(frames: list[tuple[float, str]], q: float, variables: dict[str, float]) -> float:
        values = []
        for tm, expression in frames:
            try:
                values.append((tm, evaluate(expression, variables)))
            except (ValueError, IndexError):
                values.append((tm, 0.0))
        if q <= values[0][0]:
            return values[0][1]
        for (t1, v1), (t2, v2) in zip(values, values[1:], strict=False):
            if q <= t2:
                f = 0.0 if t2 == t1 else (q - t1) / (t2 - t1)
                return v1 + (v2 - v1) * f
        return values[-1][1]

    def frame(self, t: float, states: dict[str, State] | None = None) -> Image.Image:
        canvas = Image.new("RGBA", (self.width, self.height), self.scene.background + (255,))
        for node in self.scene.nodes:
            sprite = self.sprites.get(node.id)
            s = (states or {}).get(node.id) or self.state(node, t)
            if sprite is None or not s.visible or s.alpha <= 0:
                continue
            self._place(canvas, node, sprite, s)
        return canvas

    def _place(self, canvas: Image.Image, node: Node, sprite: Sprite, s: State) -> None:
        image = sprite.image
        cx, cy = sprite.cx, sprite.cy
        if s.place[0] is not None:
            cx = s.place[0] * self.width
        if s.place[1] is not None:
            cy = s.place[1] * self.height
        cx += s.dx * self.width
        cy += s.dy * self.height
        if s.scale != 1.0 or s.scale_y != 1.0:
            nw, nh = max(1, round(image.width * s.scale)), max(1, round(image.height * s.scale_y))
            if nw * nh > MAX_SPRITE_PIXELS:
                return
            image = image.resize((nw, nh), Image.Resampling.BILINEAR)
        if s.rot:
            image = image.rotate(-s.rot, resample=Image.Resampling.BILINEAR, expand=True)
        if s.reveal is not None:
            image = self._reveal(image, *s.reveal)
        if s.alpha < 1.0:
            image = image.copy()
            image.putalpha(
                ImageChops.multiply(
                    image.getchannel("A"), Image.new("L", image.size, round(255 * s.alpha))
                )
            )
        _paste(canvas, image, round(cx - image.width / 2), round(cy - image.height / 2))

    @staticmethod
    def _reveal(image: Image.Image, filt: str, p: float) -> Image.Image:
        """Part of the picture, as a wipe or a wheel shows it; anything else fades."""
        w, h = image.size
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        wipe = re.match(r"wipe\((\w+)\)", filt)
        wheel = re.match(r"wheel\((\d+)\)", filt)
        if wipe:
            side = wipe.group(1)
            if side == "left":
                draw.rectangle((0, 0, w * p, h), fill=255)
            elif side == "right":
                draw.rectangle((w * (1 - p), 0, w, h), fill=255)
            elif side == "up":
                draw.rectangle((0, 0, w, h * p), fill=255)
            else:
                draw.rectangle((0, h * (1 - p), w, h), fill=255)
        elif wheel:
            spokes = max(1, int(wheel.group(1)))
            reach = math.hypot(w, h)
            for i in range(spokes):
                start = -90 + 360 * i / spokes
                draw.pieslice(
                    (w / 2 - reach, h / 2 - reach, w / 2 + reach, h / 2 + reach),
                    start,
                    start + 360 / spokes * p,
                    fill=255,
                )
        else:
            mask = Image.new("L", (w, h), round(255 * p))
        out = image.copy()
        out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
        return out


# ---------------------------------------------------------------- video


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found, import-untyped, unused-ignore]

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def render_video(
    deck: Path,
    number: int,
    output: Path,
    *,
    fps: int = 24,
    width: int = 1280,
    max_seconds: float = MAX_SECONDS,
    report: dict | None = None,
) -> dict:
    """Plays slide `number` of `deck` to an MP4 at `output`. Returns what it did."""
    with zipfile.ZipFile(deck) as archive:
        part = slide_part(archive, number)
        root = SafeET.fromstring(archive.read(part))
        scene = read_scene(archive, part)
    timeline = parse_timeline(root)
    if not timeline.effects and not timeline.cues:
        raise ValueError("This slide has no animation to play.")
    seconds = min(max_seconds, timeline.end_ms / 1000 + 0.5)
    player = Player(scene, timeline, width)
    frames = int(seconds * fps)
    with tempfile.TemporaryDirectory() as work:
        audio = _audio_inputs(scene, timeline, Path(work), seconds)
        command = [
            _ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{player.width}x{player.height}",
            "-r",
            str(fps),
            "-i",
            "-",
        ]
        for path, _, _, _ in audio:
            command += ["-i", str(path)]
        if audio:
            parts = []
            for i, (_, delay, (start, length), volume) in enumerate(audio, start=1):
                trim = f"atrim=start={start / 1000:.3f}" + (
                    f":duration={length / 1000:.3f}" if length else ""
                )
                parts.append(
                    f"[{i}:a]{trim},asetpts=PTS-STARTPTS,volume={volume:.3f},"
                    f"adelay={int(delay)}|{int(delay)}[a{i}]"
                )
            mix = "".join(f"[a{i}]" for i in range(1, len(audio) + 1))
            parts.append(
                f"{mix}amix=inputs={len(audio)}:normalize=0,atrim=duration={seconds:.3f}[aout]"
            )
            command += [
                "-filter_complex",
                ";".join(parts),
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        else:
            command += ["-map", "0:v"]
        command += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-sn",
            "-dn",
            "-map_chapters",
            "-1",
            "-map_metadata",
            "-1",
            "-t",
            f"{seconds:.3f}",
            "-movflags",
            "+faststart",
            str(output),
        ]
        drawn = 0
        # `with` closes ffmpeg's pipes whatever happens; a failure kills it first.
        with subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as process:  # noqa: S603  # nosec B603 -- fixed argv, no shell; the files are our own temp files
            if process.stdin is None or process.stderr is None:
                raise RuntimeError("ffmpeg did not start")
            try:
                last_key, last_bytes = None, b""
                for n in range(frames):
                    t = n / fps * 1000
                    states = {node.id: player.state(node, t) for node in scene.nodes}
                    key = tuple(s.key() for s in states.values())
                    if key != last_key:
                        last_bytes = player.frame(t, states).convert("RGB").tobytes()
                        last_key, drawn = key, drawn + 1
                    process.stdin.write(last_bytes)
                process.stdin.close()
                error = process.stderr.read().decode("utf-8", "replace")
                if process.wait() != 0:
                    raise RuntimeError("ffmpeg could not make the video: " + error[-400:])
            except BaseException:
                process.kill()
                raise
    summary = {
        "seconds": round(seconds, 1),
        "frames": frames,
        "framesDrawn": drawn,
        "fps": fps,
        "size": [player.width, player.height],
        "effects": len(timeline.effects),
        "soundCues": len(audio),
        "notes": timeline.notes,
    }
    if report is not None:
        report.update(summary)
    return summary


def _audio_inputs(
    scene: Scene, timeline: Timeline, work: Path, seconds: float
) -> list[tuple[Path, float, tuple[float, float], float]]:
    found = []
    for i, cue in enumerate(timeline.cues):
        node = scene.by_id.get(cue.shape)
        if node is None or not node.audio or cue.start / 1000 >= seconds:
            continue
        data = scene.media.get(node.audio)
        if data is None:
            continue
        path = work / f"cue{i}{Path(node.audio).suffix or '.wav'}"
        path.write_bytes(data)
        start = (node.trim[0] if node.trim else 0.0) + cue.offset * 1000
        length = cue.dur if cue.dur else ((node.trim[1] - node.trim[0]) if node.trim else 0.0)
        found.append((path, cue.start, (start, length), timeline.volumes.get(cue.shape, 1.0)))
    return found


def _pt(dimension: dict) -> float:
    """A Slides size in points, whichever unit it is stated in."""
    return dimension.get("magnitude", 0) / (1 if dimension.get("unit") == "PT" else EMU_PER_PT)


def match_recordings(deck_name: str, names: list[str]) -> dict[int, str]:
    """The recordings staff made for this deck, by slide number.

    They are named after the deck and the slide: `Lesson 2 - slide 6.mp4`. The
    deck's name is matched exactly, so one deck's recording is never taken for
    another's, and any dash is accepted between the name and the word "slide".
    """
    stem = Path(deck_name).stem
    pattern = re.compile(rf"^{re.escape(stem)}\s*[-–—]\s*slide\s+(\d+)\.mp4$", re.IGNORECASE)
    found: dict[int, str] = {}
    for name in sorted(names):
        match = pattern.match(name)
        if match and int(match.group(1)) >= 1:
            found.setdefault(int(match.group(1)), name)
    return found


def select_slides(deck: Path, min_effects: int = HEAVY_EFFECTS) -> list[int]:
    """The slides worth recording: those with this many effects or more.

    A click-to-reveal slide has a few; a timed scene has dozens. The simple
    ones are better kept as slides than as video.
    """
    chosen = []
    with zipfile.ZipFile(deck) as archive:
        for number, part in enumerate(slide_parts(archive), start=1):
            timeline = parse_timeline(SafeET.fromstring(archive.read(part)))
            if len(timeline.effects) >= min_effects:
                chosen.append(number)
    return chosen


async def attach(
    google: Any,
    presentation_id: str,
    folder_id: str,
    deck: Path,
    slides: list[int],
    *,
    render: Any = render_video,
    recordings: dict[int, Path] | None = None,
) -> tuple[dict, list[dict]]:
    """Records each slide, saves the video in the conversion folder, and puts it on the slide.

    The video replaces what the slide held: those pictures were the scene's
    parts, piled up with nothing to play them. One slide at a time, so a slide
    that cannot be played or placed costs only itself; a video that was saved
    but could not be placed stays in the folder, and the slide is left alone.
    Whoever opens the deck needs access to the video file to play it.
    """
    summary = {"saved": 0, "placed": 0, "failed": 0}
    notes: list[dict] = []
    for number in slides:
        with tempfile.TemporaryDirectory() as work:
            out = Path(work) / f"slide{number}.mp4"
            try:
                made = (recordings or {}).get(number)
                if made is not None:
                    # A recording staff made in PowerPoint is exact: used as it is.
                    await asyncio.to_thread(shutil.copyfile, made, out)
                else:
                    await asyncio.to_thread(render, deck, number, out)
                saved = await google.upload(
                    out, f"Slide {number} animation.mp4", "video/mp4", folder_id, retry=True
                )
                summary["saved"] += 1
            except Exception as error:  # noqa: BLE001  # one slide never stops the rest
                summary["failed"] += 1
                # For whoever runs the migration: why, in the log. The report
                # keeps a plain sentence (ffmpeg's own words stay out of it).
                logger.warning(
                    json.dumps(
                        {
                            "event": "animation_video_failed",
                            "slide": number,
                            "error": type(error).__name__,
                            "code": getattr(error, "code", ""),
                            "reason": str(getattr(error, "detail", None) or error)[:300],
                        }
                    )
                )
                reason = (
                    str(error) if isinstance(error, ValueError) else "It could not be recorded."
                )
                notes.append(
                    warning(
                        "animation_video_failed",
                        f"Slide {number}'s animation was not recorded. {reason}",
                        classification=C.UNSUPPORTED,
                        slideIndex=number - 1,
                    )
                )
                continue
        try:
            presentation = await google.inspect(presentation_id)
            page = presentation["slides"][number - 1]
            width = _pt(presentation["pageSize"]["width"])
            height = _pt(presentation["pageSize"]["height"])
            requests: list[dict] = [
                {
                    "createVideo": {
                        "objectId": f"wmt_animation_{number}",
                        "elementProperties": {
                            "pageObjectId": page["objectId"],
                            "size": {
                                "width": {"magnitude": width, "unit": "PT"},
                                "height": {"magnitude": height, "unit": "PT"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": 0,
                                "translateY": 0,
                                "unit": "PT",
                            },
                        },
                        "source": "DRIVE",
                        "id": saved["id"],
                    }
                }
            ]
            requests += [
                {"deleteObject": {"objectId": element["objectId"]}}
                for element in page.get("pageElements", [])
            ]
            await google.slides_batch(presentation_id, requests)
        except (IndexError, KeyError, ToolkitError):
            summary["failed"] += 1
            notes.append(
                warning(
                    "animation_video_saved_only",
                    f"Slide {number}'s animation was recorded and saved in the conversion "
                    "folder, but could not be put on the slide. The slide is as it was.",
                    classification=C.SUBSTITUTED,
                    slideIndex=number - 1,
                )
            )
            continue
        summary["placed"] += 1
        notes.append(
            warning(
                "animation_video_placed",
                f"Slide {number}'s animation was recorded as a video and put on the slide in "
                "place of its pictures. The video is saved in the conversion folder; anyone "
                "who plays the deck needs access to it.",
                classification=C.SUBSTITUTED,
                slideIndex=number - 1,
            )
        )
    return summary, notes


def main(argv: list[str] | None = None) -> None:
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description="Play a slide's animation to video (prototype).")
    commands = parser.add_subparsers(dest="command", required=True)

    render_cmd = commands.add_parser("render", help="play one slide to an MP4")
    render_cmd.add_argument("deck", type=Path)
    render_cmd.add_argument("slide", type=int)
    render_cmd.add_argument("output", type=Path)
    render_cmd.add_argument("--fps", type=int, default=24)
    render_cmd.add_argument("--width", type=int, default=1280)
    render_cmd.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    render_cmd.add_argument(
        "--png-at", default="", help="comma-separated seconds: save a still of each"
    )

    select_cmd = commands.add_parser("select", help="list the slides worth recording")
    select_cmd.add_argument("deck", type=Path)
    select_cmd.add_argument("--min-effects", type=int, default=20)

    attach_cmd = commands.add_parser(
        "attach",
        help="put a video on each animated slide of an already converted deck "
        "(the token is read from GOOGLE_ACCESS_TOKEN)",
    )
    attach_cmd.add_argument("deck", type=Path, help="the original .pptx")
    attach_cmd.add_argument("presentation", help="the converted Slides deck's id")
    attach_cmd.add_argument("folder", help="the conversion folder's id")
    attach_cmd.add_argument("--slides", default="auto", help="'auto' or numbers such as 6,9")
    attach_cmd.add_argument(
        "--recordings-dir",
        type=Path,
        help="a folder of recordings named like 'DECK NAME - slide 6.mp4'; used instead of playing",
    )
    args = parser.parse_args(argv)

    if args.command == "select":
        print(json.dumps(select_slides(args.deck, args.min_effects)))
        return
    if args.command == "attach":
        import httpx

        from .google import Google

        recordings: dict[int, Path] = {}
        if args.recordings_dir:
            names = [p.name for p in args.recordings_dir.iterdir() if p.is_file()]
            recordings = {
                n: args.recordings_dir / name
                for n, name in match_recordings(args.deck.name, names).items()
            }
        wanted = (
            select_slides(args.deck)
            if args.slides == "auto"
            else [int(n) for n in args.slides.split(",") if n.strip()]
        )
        slides = sorted(set(wanted) | set(recordings))

        async def go() -> None:
            async with httpx.AsyncClient(timeout=300) as client:
                google = Google(os.environ["GOOGLE_ACCESS_TOKEN"], client)
                summary, notes = await attach(
                    google, args.presentation, args.folder, args.deck, slides, recordings=recordings
                )
                print(
                    json.dumps(
                        {"slides": slides, "usedRecordings": sorted(recordings), **summary},
                        indent=2,
                    )
                )
                print(json.dumps([n["code"] for n in notes]))

        asyncio.run(go())
        return
    if args.png_at:
        with zipfile.ZipFile(args.deck) as archive:
            part = slide_part(archive, args.slide)
            root = SafeET.fromstring(archive.read(part))
            scene = read_scene(archive, part)
        player = Player(scene, parse_timeline(root), args.width)
        for second in args.png_at.split(","):
            still = args.output.with_name(f"{args.output.stem}-{second}s.png")
            player.frame(float(second) * 1000).convert("RGB").save(still)
            print("saved", still.name)
    print(
        json.dumps(
            render_video(
                args.deck,
                args.slide,
                args.output,
                fps=args.fps,
                width=args.width,
                max_seconds=args.max_seconds,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
