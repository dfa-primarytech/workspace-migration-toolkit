"""A drawn shape's coverage masks stay within a memory budget (#111). The
picture is capped at Slides' pixel limit, but its masks are drawn larger and
averaged down; a path reaching far off the page made one mask 210 MiB. Sizes
are checked by recording them, not by allocating a huge mask here."""

from __future__ import annotations

import pytest
from PIL import Image
from workspace_toolkit import publisher_art
from workspace_toolkit.publisher_art import (
    MASK_BUDGET,
    SUPERSAMPLE,
    Subpath,
    _canvas,
    _supersample,
    draw_path,
)

FILLED = {"draw:fill": "solid", "draw:fill-color": "#336699", "draw:stroke": "none"}
BOTH = {**FILLED, "draw:stroke": "solid", "svg:stroke-color": "#000000", "svg:stroke-width": "2pt"}


def square(side: float) -> list[Subpath]:
    return [Subpath([(0, 0), (side, 0), (side, side), (0, side)], closed=True)]


def test_a_page_sized_shape_is_still_drawn_at_full_smoothness():
    _, w, h = _canvas((0, 0, 420, 595))  # A5
    assert _supersample(w, h) == SUPERSAMPLE


def test_the_largest_picture_slides_takes_gets_a_mask_within_budget():
    _, w, h = _canvas((0, 0, 100_000, 100_000))  # a path far off the page
    big = _supersample(w, h)
    assert big < SUPERSAMPLE
    assert w * h * big * big <= MASK_BUDGET


@pytest.mark.parametrize("big", [1, 2, 3])
def test_the_budget_picks_the_most_it_can_afford(big):
    side = int((MASK_BUDGET / big**2) ** 0.5)
    assert _supersample(side, side) == big


def test_every_mask_drawn_keeps_to_the_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher_art, "MASK_BUDGET", 2_000_000)
    sizes: list[tuple[int, int]] = []
    real = Image.new

    def recording(mode, size, *args, **kwargs):
        if mode == "L":
            sizes.append(size)
        return real(mode, size, *args, **kwargs)

    monkeypatch.setattr(publisher_art.Image, "new", recording)
    drawn = draw_path("shape", square(200), BOTH, tmp_path)
    assert drawn is not None
    assert len(sizes) == 2  # the fill's mask, then the outline's
    # The picture itself is the size it always was; its masks drop to 2x.
    _, w, h = _canvas(drawn.box)
    assert (drawn.picture.width, drawn.picture.height) == (w, h)
    assert sizes == [(w * 2, h * 2)] * 2
    assert all(mw * mh <= 2_000_000 for mw, mh in sizes)
