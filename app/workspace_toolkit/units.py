"""Units and placement, in one place (PROJECT.md §19).

The Publisher IR is in points throughout, but its raw librevenge properties
carry lengths as strings ("0.3937in"), and Google Slides places an element as
a size plus an affine transform. Every conversion between those lives here,
so renderer code never does unit arithmetic of its own.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

POINTS_PER_INCH = 72.0
EMU_PER_POINT = 12700

_LENGTH = re.compile(r"^\s*(-?\d+(?:\.\d+)?(?:[eE]-?\d+)?)\s*(in|pt|cm|mm|\*|%)?\s*$")
_TO_POINTS = {
    "in": POINTS_PER_INCH,
    "pt": 1.0,
    "cm": POINTS_PER_INCH / 2.54,
    "mm": POINTS_PER_INCH / 25.4,
    "*": 1 / 20,  # librevenge writes twips with a '*'
    None: 1.0,  # librevenge's "generic" unit is points
}


def inches_to_points(value: float) -> float:
    return value * POINTS_PER_INCH


def mm_to_points(value: float) -> float:
    return value * _TO_POINTS["mm"]


def points_to_mm(value: float) -> float:
    return value / _TO_POINTS["mm"]


def emu_to_points(value: float) -> float:
    return value / EMU_PER_POINT


def length_points(value: object) -> float | None:
    """A librevenge length string in points; None for a percentage or nonsense."""
    if not isinstance(value, str):
        return None
    match = _LENGTH.match(value)
    if not match or match.group(2) == "%":
        return None
    return float(match.group(1)) * _TO_POINTS[match.group(2)]


def percentage(value: object) -> float | None:
    """'115%' → 115.0; anything else → None."""
    if not isinstance(value, str):
        return None
    match = _LENGTH.match(value)
    if not match or match.group(2) != "%":
        return None
    return float(match.group(1))


@dataclass(frozen=True)
class Frame:
    """An element's unrotated box, placed by its centre, turned `rotation`
    degrees counter-clockwise on the page (the IR's convention)."""

    width: float
    height: float
    cx: float
    cy: float
    rotation: float = 0.0

    @classmethod
    def from_bounds(cls, x: float, y: float, width: float, height: float, rotation=0.0) -> Frame:
        return cls(width, height, x + width / 2, y + height / 2, rotation or 0.0)

    @classmethod
    def from_outline(cls, points: list[tuple[float, float]]) -> Frame | None:
        """The frame of a (possibly rotated) rectangle given as its outline:
        top-left, top-right, bottom-right, bottom-left, optionally closed."""
        if len(points) >= 5 and points[0] == points[-1]:
            points = points[:-1]
        if len(points) != 4:
            return None
        (x0, y0), (x1, y1), _, (x3, y3) = points
        width = math.hypot(x1 - x0, y1 - y0)
        height = math.hypot(x3 - x0, y3 - y0)
        if width <= 0 or height <= 0:
            return None
        cx = sum(p[0] for p in points) / 4
        cy = sum(p[1] for p in points) / 4
        # y points down the page, so a counter-clockwise turn has a negative dy.
        rotation = math.degrees(math.atan2(-(y1 - y0), x1 - x0)) % 360
        return cls(width, height, cx, cy, rotation)

    def corners(self) -> list[tuple[float, float]]:
        """Top-left, top-right, bottom-right, bottom-left, as drawn on the page."""
        return [
            apply(self.transform(self.width, self.height), (u, v))
            for u, v in ((0, 0), (self.width, 0), (self.width, self.height), (0, self.height))
        ]

    def transform(self, width: float, height: float) -> dict:
        """The Slides transform that draws a `width` × `height` element in this frame.

        Slides maps an element's own point (u, v) to
        (scaleX·u + shearX·v + translateX, shearY·u + scaleY·v + translateY),
        so a different natural size is stretched to fit, and the turn is about
        the frame's centre, as in Publisher.
        """
        sx, sy = self.width / width, self.height / height
        # Clockwise on screen is what a positive angle means once y points down.
        turn = math.radians(-self.rotation)
        cos, sin = math.cos(turn), math.sin(turn)
        a, b, c, d = cos * sx, -sin * sy, sin * sx, cos * sy
        return {
            "scaleX": _clean(a),
            "shearX": _clean(b),
            "shearY": _clean(c),
            "scaleY": _clean(d),
            "translateX": _clean(self.cx - (a * width + b * height) / 2),
            "translateY": _clean(self.cy - (c * width + d * height) / 2),
            "unit": "PT",
        }


def apply(transform: dict, point: tuple[float, float]) -> tuple[float, float]:
    u, v = point
    return (
        transform["scaleX"] * u + transform["shearX"] * v + transform["translateX"],
        transform["shearY"] * u + transform["scaleY"] * v + transform["translateY"],
    )


def size(width: float, height: float) -> dict:
    return {
        "width": {"magnitude": _clean(width), "unit": "PT"},
        "height": {"magnitude": _clean(height), "unit": "PT"},
    }


def _clean(value: float) -> float:
    """Round away float noise (1e-17 shears) without losing real precision."""
    rounded = round(value, 6)
    return 0.0 if rounded == 0 else rounded
