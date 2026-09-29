"""Text that wrapped around a picture in Publisher, recreated with indents.

Google Slides cannot wrap text around a picture: text runs straight under
it. Publisher wraps text around any object in front of its frame, so a
converted page had text hidden behind its pictures (PUB-001's frog, on page
2). Slides can indent each paragraph separately, so the paragraphs level
with a picture are indented just enough to clear it, on the side the picture
is on. The text stays in one editable box, and the indents are ordinary
paragraph indents.

Positions come from publisher_fit's layout (Google's own line geometry,
within a couple of points on PUB-001). Indenting changes how lines wrap and
the fit changes spacing, so the two are repeated until they settle.

What this cannot do, and reports instead:

- wrap on both sides of a picture (Slides has no columns inside a box): the
  text keeps to the side with more room;
- wrap part of a paragraph: the whole paragraph is indented, which costs a
  little height the fit then absorbs;
- wrap around a picture covering most of the line: the text would be a
  sliver, so the picture stays over it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .publisher_fit import INSET_X, INSET_Y, Fit, Para, fit, layout

GAP = 3.6  # points between text and a picture it wraps around
MAX_SHARE = 0.6  # of the line: a picture needing more is not wrapped around
ROUNDS = 5


@dataclass(frozen=True)
class Obstacle:
    """A picture in front of the text, as its box on the page."""

    element_id: str
    left: float
    top: float
    right: float
    bottom: float


@dataclass
class Wrapped:
    extra: dict[int, tuple[float, float]]  # paragraph → (added start indent, added end indent)
    fitted: Fit | None
    around: list[str] = field(default_factory=list)  # obstacles the text keeps clear of
    under: list[str] = field(default_factory=list)  # obstacles too wide to keep clear of


def _indented(paras: list[Para], extra: dict[int, tuple[float, float]]) -> list[Para]:
    out = []
    for index, para in enumerate(paras):
        start, end = extra.get(index, (0.0, 0.0))
        out.append(
            replace(
                para,
                indent_start=para.indent_start + start,
                indent_first=para.indent_first + start,
                indent_end=para.indent_end + end,
            )
        )
    return out


def spans(
    paras: list[Para], width: float, spacing: float | None, scale: float, top: float
) -> list[tuple[float, float]]:
    """Where each paragraph starts and ends down the page, in points."""
    out = []
    y = top
    for para in paras:
        height = sum(h for _, h in layout([para], width, spacing, scale))
        out.append((y, y + height))
        y += height
    return out


def wrap(
    paras: list[Para],
    box: tuple[float, float, float, float],
    obstacles: list[Obstacle],
) -> Wrapped | None:
    """The indents that keep the text clear of `obstacles`, and the fit with them.

    None when the text cannot be measured (a font without measurements).
    """
    x, y, width, height = box
    inner_left, inner_right = x + INSET_X, x + width - INSET_X
    line = inner_right - inner_left
    middle = (inner_left + inner_right) / 2
    sides: list[tuple[Obstacle, float, float]] = []
    wide: list[Obstacle] = []
    for o in obstacles:
        if o.right <= inner_left or o.left >= inner_right or o.bottom <= y or o.top >= y + height:
            continue  # not over this text
        if (o.left + o.right) / 2 >= middle:
            start, end = 0.0, max(0.0, inner_right - o.left + GAP)
        else:
            start, end = max(0.0, o.right - inner_left + GAP), 0.0
        if max(start, end) > line * MAX_SHARE:
            wide.append(o)
        else:
            sides.append((o, start, end))
    fitted = fit(paras, width, height)
    if fitted is None:
        return None
    if not sides and not wide:
        return Wrapped({}, fitted)

    extra: dict[int, tuple[float, float]] = {}
    previous: dict[int, tuple[float, float]] = {}
    for _ in range(ROUNDS):
        laid = _indented(paras, extra)
        where = spans(
            laid,
            line,
            fitted.line_spacing if fitted else None,
            fitted.scale if fitted else 1.0,
            y + INSET_Y,
        )
        new: dict[int, tuple[float, float]] = {}
        for index, (top, bottom) in enumerate(where):
            start = end = 0.0
            for o, o_start, o_end in sides:
                if _level(top, bottom, o):
                    start, end = max(start, o_start), max(end, o_end)
            # An author often indented these by hand already: only make up
            # the shortfall, never add to it.
            start = max(0.0, start - paras[index].indent_start)
            end = max(0.0, end - paras[index].indent_end)
            if start or end:
                new[index] = (start, end)
        if new == extra:
            break
        previous, extra = extra, new
        fitted = fit(_indented(paras, extra), width, height)
    else:
        # Still moving: indent everything either round asked for, so no line
        # is left under a picture.
        for index, (start, end) in previous.items():
            now = extra.get(index, (0.0, 0.0))
            extra[index] = (max(start, now[0]), max(end, now[1]))
        fitted = fit(_indented(paras, extra), width, height)
    # Report only the pictures that are level with some text.
    where = spans(
        _indented(paras, extra),
        line,
        fitted.line_spacing if fitted else None,
        fitted.scale if fitted else 1.0,
        y + INSET_Y,
    )
    beside = [o.element_id for o, _, _ in sides if any(_level(t, b, o) for t, b in where)]
    over = [o.element_id for o in wide if any(_level(t, b, o) for t, b in where)]
    return Wrapped(extra, fitted, beside, over)


def _level(top: float, bottom: float, o: Obstacle) -> bool:
    """Whether a paragraph from `top` to `bottom` is level with the obstacle."""
    return top < o.bottom + GAP and bottom > o.top - GAP
