"""Fitting a Publisher text frame's text inside its box, in the font Slides uses.

Publisher sized every frame to its text in the original font. A substituted
font takes different room: Andika, which replaces Sassoon Primary, has wider
letters, so the same text wraps onto more lines and runs past its box, off the
page or under the picture beside it. PUB-001's live run showed both.

Before the requests are written, each frame is laid out here, a line at a
time, with the font's real advance widths and vertical metrics (extracted by
scripts/font_metrics.py, so no font file ships). If it would overflow:

1. tighten the line spacing a little, to no less than SPACING_FLOOR;
2. only then make the text smaller, evenly, and never below MIN_SCALE,
   because size matters more than spacing to a young reader.

Google lays lines out 1.2 times the font size apart at 100% spacing, whatever
the font: measured on the live PUB-001 slides (2026-09-29), not the 1.61 that
Andika's own metrics give. Its space inside a text box measured 7.2 pt at the
sides, PowerPoint's 0.1 inch.

Every change is reported. A frame that still overflows is reported too. The
layout is an estimate, not Google's own: it keeps a margin, and a frame in a
font it has no measurements for is left as it is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

from .fonts import normalise_family

METRICS = Path(__file__).parent / "font_metrics"
# Google's space inside a text box: 7.2 pt at the sides, measured live; above
# and below assumed to be PowerPoint's 0.05 in. The API exposes neither.
INSET_X = 7.2
INSET_Y = 3.6
LINE = 1.2  # Google's line height at 100% spacing, in ems: measured live
TAB = 36.0  # points to the next default tab stop, half an inch
SAFETY = 0.97  # of the room available: the layout is an estimate
SPACING_FLOOR = 90  # percent: closer than this and lines start to crowd
SPACING_STEP = 5  # percent
SCALE_STEP = 0.05
MIN_SCALE = 0.75


@dataclass(frozen=True)
class Style:
    family: str | None
    size: float
    bold: bool = False
    italic: bool = False


@dataclass
class Para:
    runs: list[tuple[str, Style]]
    indent_start: float = 0.0
    indent_first: float = 0.0
    indent_end: float = 0.0
    space_above: float = 0.0
    space_below: float = 0.0
    line_spacing: float | None = None  # percent of the font's own, as Slides has it


@dataclass
class Fit:
    line_spacing: float | None = None  # percent to set on every paragraph, if tightened
    scale: float = 1.0  # applied to every font size
    overflows: bool = False
    height: float = 0.0  # laid-out height, in points
    notes: list[dict] = field(default_factory=list)


def known(family: str) -> dict:
    """Measurements for a family `measurable` has already accepted."""
    data = metrics(family)
    if data is None:
        raise KeyError(family)
    return data


@cache
def metrics(family: str) -> dict | None:
    path = METRICS / f"{normalise_family(family).replace(' ', '')}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for style in data["styles"].values():
        style["widths"] = {int(k): v for k, v in style["widths"].items()}
    return data


def measurable(family: str | None) -> bool:
    return bool(family) and metrics(family) is not None  # type: ignore[arg-type]


def em(family: str) -> float:
    """The font's own line height, in ems (for reference: Google does not use it)."""
    data = known(family)
    return (data["ascent"] + data["descent"] + data["lineGap"]) / data["unitsPerEm"]


def sized(size: float, scale: float) -> float:
    """A font size as Slides receives it: scaled, to the nearest half point."""
    return size if scale == 1.0 else round(size * scale * 2) / 2


def advance(ch: str, style: Style, scale: float) -> float:
    if ch == "\t":
        return TAB
    data = known(style.family or "")
    key = ("bold" if style.bold else "") + ("Italic" if style.italic else "")
    table = data["styles"][
        {"": "regular", "bold": "bold", "Italic": "italic"}.get(key, "boldItalic")
    ]
    units = table["widths"].get(ord(ch), table["average"])
    return units / data["unitsPerEm"] * sized(style.size, scale)


def _pitch(styles: list[Style], spacing: float, scale: float) -> float:
    return max(sized(s.size, scale) for s in styles) * LINE * spacing / 100


def height(paras: list[Para], width: float, spacing: float | None, scale: float) -> float:
    """How tall the frame's text lays out, greedily wrapping at spaces."""
    return sum(pitch for _, pitch in layout(paras, width, spacing, scale))


def layout(
    paras: list[Para], width: float, spacing: float | None, scale: float
) -> list[tuple[str, float]]:
    """Each line the text wraps to, as (kind, height): "line" or "space"."""
    out: list[tuple[str, float]] = []
    for para in paras:
        own = para.line_spacing or 100.0
        used = min(own, spacing) if spacing is not None else own
        chars = [(ch, style) for text, style in para.runs for ch in text]
        default = para.runs[0][1] if para.runs else Style("", 12)
        lines: list[list[Style]] = []
        line: list[Style] = []
        room = width - para.indent_first - para.indent_end
        filled = 0.0
        word = 0.0
        word_styles: list[Style] = []
        for ch, style in chars + [("\u000b", default)]:
            if ch == "\u000b":  # a line break, or the end of the paragraph
                if filled + word > room and filled:
                    lines.append(line)
                    line, filled = [], 0.0
                    room = width - para.indent_start - para.indent_end
                lines.append(line + word_styles or [default])
                line, filled, word, word_styles = [], 0.0, 0.0, []
                room = width - para.indent_start - para.indent_end
                continue
            size = advance(ch, style, scale)
            if ch in " \t":
                if filled + word > room and filled:
                    lines.append(line)
                    line, filled = [], 0.0
                    room = width - para.indent_start - para.indent_end
                line += word_styles + [style]
                filled += word + size
                word, word_styles = 0.0, []
                continue
            word += size
            word_styles.append(style)
            if word > room and not filled:  # one word wider than the line: it breaks
                lines.append(word_styles[:-1] or [style])
                word, word_styles = size, [style]
                room = width - para.indent_start - para.indent_end
        if para.space_above:
            out.append(("space", para.space_above))
        out += [("line", _pitch(styles, used, scale)) for styles in lines]
        if para.space_below:
            out.append(("space", para.space_below))
    return out


def largest(
    lines: list[str], style: Style, box_width: float, box_height: float, floor: float = 6.0
) -> float:
    """The largest size, up to `style.size`, at which each line fits the box
    without wrapping and all of them fit its height: WordArt fills its frame."""
    width = box_width - 2 * INSET_X
    room = (box_height - 2 * INSET_Y) * SAFETY
    size = style.size
    while size > floor:
        trial = replace(style, size=size)
        wide = max(sum(advance(ch, trial, 1.0) for ch in line) for line in lines)
        if wide <= width and len(lines) * size * LINE <= room:
            return size
        size -= 0.5
    return floor


def fit(paras: list[Para], box_width: float, box_height: float) -> Fit | None:
    """What it takes for the text to fit, or None if it cannot be measured."""
    styles = [style for para in paras for _, style in para.runs]
    if not styles or not all(measurable(s.family) for s in styles):
        return None
    width = box_width - 2 * INSET_X
    room = (box_height - 2 * INSET_Y) * SAFETY
    natural = height(paras, width, None, 1.0)
    if natural <= room:
        return Fit(height=natural)
    floor = SPACING_FLOOR
    spacing = 100
    while spacing - SPACING_STEP >= floor:
        spacing -= SPACING_STEP
        laid = height(paras, width, spacing, 1.0)
        if laid <= room:
            return Fit(spacing, 1.0, False, laid, [_tightened()])
    spacing = floor
    scale = 1.0
    while round(scale - SCALE_STEP, 2) >= MIN_SCALE:
        scale = round(scale - SCALE_STEP, 2)
        laid = height(paras, width, spacing, scale)
        if laid <= room:
            return Fit(spacing, scale, False, laid, [_tightened(), _smaller(scale)])
    laid = height(paras, width, spacing, scale)
    return Fit(
        spacing,
        scale,
        True,
        laid,
        [
            _tightened(),
            _smaller(scale),
            {
                "code": "text-overflows",
                "message": "Even so, the text may still run past its box: check this page.",
            },
        ],
    )


def _tightened() -> dict:
    return {
        "code": "text-spacing-tightened",
        "message": "Lines were set a little closer together so the text fits its box.",
    }


def _smaller(scale: float) -> dict:
    return {
        "code": "text-made-smaller",
        "message": f"Text was made smaller (to {round(scale * 100)}%) so it fits its box.",
    }
