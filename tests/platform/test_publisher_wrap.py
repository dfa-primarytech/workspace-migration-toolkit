"""Text kept clear of pictures in front of it, as Publisher wrapped it.

Slides cannot wrap text, so the paragraphs level with a picture are indented
on the picture's side. Documents are built in the test.
"""

from __future__ import annotations

import pytest
from workspace_toolkit.publisher_fit import INSET_X, Para, Style
from workspace_toolkit.publisher_slides import check, plan
from workspace_toolkit.publisher_wrap import GAP, Obstacle, wrap

from .test_publisher_slides import document, paragraph, pictures, report, requests, run, text_box
from .test_publisher_slides import image as picture

ANDIKA = Style("Andika", 12)
LINE = "Your child will bring home a book to share with you at home each week. "


def para(text: str = LINE, **extra) -> Para:
    return Para([(text, ANDIKA)], **extra)


BOX = (20.0, 20.0, 380.0, 540.0)  # x, y, width, height


def test_paragraphs_level_with_a_picture_on_the_right_are_indented_to_clear_it():
    paras = [para() for _ in range(12)]
    frog = Obstacle("frog", 300, 150, 395, 220)
    result = wrap(paras, BOX, [frog])
    assert result is not None and result.around == ["frog"]
    need = (20 + 380 - INSET_X) - 300 + GAP
    assert result.extra and all(
        end == pytest.approx(need) and start == 0 for start, end in result.extra.values()
    )
    assert 0 not in result.extra  # the first paragraph is above the picture
    assert max(result.extra) < 11  # nor the last, below it


def test_a_picture_on_the_left_indents_the_start_and_the_first_line():
    paras = [para() for _ in range(6)]
    result = wrap(paras, BOX, [Obstacle("logo", 25, 30, 120, 90)])
    assert result is not None
    start, end = result.extra[0]
    assert end == 0 and start == pytest.approx(120 - (20 + INSET_X) + GAP)


def test_an_authors_own_indent_is_not_added_to():
    by_hand = [para(indent_end=200.0) for _ in range(6)]
    result = wrap(by_hand, BOX, [Obstacle("pic", 300, 30, 395, 200)])
    assert result is not None and result.extra == {}  # already clear


def test_a_picture_across_most_of_the_line_is_reported_only_if_text_is_level_with_it():
    paras = [para() for _ in range(3)]
    banner = Obstacle("banner", 30, 100, 390, 160)
    below = Obstacle("qr", 30, 450, 390, 540)
    result = wrap(paras, BOX, [banner, below])
    assert result is not None
    assert result.under == ["banner"] and result.extra == {}


def test_nothing_happens_without_a_picture_over_the_text():
    paras = [para() for _ in range(3)]
    result = wrap(paras, BOX, [Obstacle("beside", 420, 30, 500, 90)])
    assert result is not None and result.extra == {} and result.around == []


def test_the_plan_indents_beside_pictures_in_front_and_ignores_those_behind(tmp_path):
    prepared = pictures(tmp_path, pic=(100, 100))
    body = [paragraph(run(LINE, font="SassoonPrimaryInfant")) for _ in range(10)]
    behind = picture("el_1", 0, (300, 60, 90, 90), "pic")
    text = text_box("el_2", 1, (20, 20, 380, 540), *body)
    front = picture("el_3", 2, (300, 160, 90, 90), "pic")
    result = plan(document([behind, text, front]), prepared, title="Test", delete=["p"])
    assert check(result, existing=["p"]) == []
    ends = [
        r["style"]["indentEnd"]["magnitude"]
        for r in requests(result, "updateParagraphStyle")
        if "indentEnd" in r["style"]
    ]
    assert ends and all(
        e == pytest.approx((20 + 380 - INSET_X) - 300 + GAP, abs=0.01) for e in ends
    )
    codes = [n["code"] for n in report(result)["el_2"]["notes"]]
    assert "text-wrapped" in codes
