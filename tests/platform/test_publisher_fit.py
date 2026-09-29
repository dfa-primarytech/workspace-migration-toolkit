"""Fitting a Publisher frame's text in the font Slides will draw it with.

The measurements are Andika's own (font_metrics/andika.json). The layout is
the fitter's estimate, not Google's; these tests pin what it decides.
"""

from __future__ import annotations

import pytest
from workspace_toolkit.publisher_art import Prepared
from workspace_toolkit.publisher_fit import (
    INSET_X,
    MIN_SCALE,
    Para,
    Style,
    advance,
    em,
    fit,
    height,
    measurable,
)
from workspace_toolkit.publisher_slides import check, plan

from .test_publisher_slides import document, paragraph, report, requests, run, text_box

ANDIKA = Style("Andika", 12)
WORDS = "Help your child to read words by saying the sounds and blending them "


def para(text: str, style: Style = ANDIKA, **extra) -> Para:
    return Para([(text, style)], **extra)


def test_andikas_measurements_are_shipped_and_its_lines_are_tall():
    assert measurable("Andika") and not measurable("Calibri") and not measurable(None)
    assert em("Andika") == pytest.approx((2500 + 800) / 2048)  # 1.61: most fonts are near 1.2
    assert advance("m", ANDIKA, 1.0) > advance("i", ANDIKA, 1.0) > 0
    assert advance("m", Style("Andika", 24), 1.0) == pytest.approx(2 * advance("m", ANDIKA, 1.0))


def test_lines_wrap_at_spaces_and_each_is_one_line_high():
    one_line = height([para("Hello")], 300, None, 1.0)
    assert one_line == pytest.approx(12 * em("Andika"))
    long = height([para(WORDS * 3)], 200, None, 1.0)
    assert long == pytest.approx(round(long / one_line) * one_line) and long >= 4 * one_line
    breaks = height([para("a\u000bb\u000bc")], 300, None, 1.0)
    assert breaks == pytest.approx(3 * one_line)


def test_text_that_fits_is_left_alone():
    result = fit([para("A short line.")], 300, 100)
    assert result is not None
    assert (result.line_spacing, result.scale, result.overflows, result.notes) == (
        None,
        1.0,
        False,
        [],
    )


def test_overflowing_text_has_its_spacing_tightened_before_it_is_made_smaller():
    paras = [para(WORDS)] * 6
    natural = height(paras, 300 - 2 * INSET_X, None, 1.0)
    tight = fit(paras, 300, natural * 0.85)
    assert tight is not None and tight.line_spacing is not None and tight.line_spacing < 100
    assert tight.scale == 1.0
    assert [n["code"] for n in tight.notes] == ["text-spacing-tightened"]
    smaller = fit(paras, 300, natural * 0.7)
    assert smaller is not None and smaller.line_spacing == round(1.2 / em("Andika") * 100)
    assert MIN_SCALE <= smaller.scale < 1.0
    assert [n["code"] for n in smaller.notes] == ["text-spacing-tightened", "text-made-smaller"]


def test_text_that_cannot_fit_is_reported_and_never_made_tiny():
    result = fit([para(WORDS * 20)], 200, 40)
    assert result is not None and result.overflows and result.scale == MIN_SCALE
    assert result.notes[-1]["code"] == "text-overflows"


def test_a_frame_in_a_font_without_measurements_is_not_touched():
    assert fit([para(WORDS * 20, Style("Calibri", 12))], 200, 40) is None


def test_the_plan_shrinks_an_overflowing_sassoon_frame_and_says_so():
    long = [paragraph(run(WORDS * 2, font="SassoonPrimaryInfant")) for _ in range(12)]
    box = text_box("el_1", 0, (20, 20, 380, 300), *long)
    result = plan(document([box]), Prepared(), title="Test", delete=["p"])
    assert check(result, existing=["p"]) == []
    spacings = {p["style"].get("lineSpacing") for p in requests(result, "updateParagraphStyle")}
    assert spacings and all(s is not None and s < 100 for s in spacings)
    sizes = {s["style"]["fontSize"]["magnitude"] for s in requests(result, "updateTextStyle")}
    assert all(size <= 12 and size * 2 == int(size * 2) for size in sizes)  # half points
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "text-spacing-tightened" in codes


def test_a_short_sassoon_frame_keeps_its_spacing():
    box = text_box(
        "el_1", 0, (20, 20, 380, 300), paragraph(run("Hello", font="SassoonPrimaryInfant"))
    )
    result = plan(document([box]), Prepared(), title="Test", delete=["p"])
    assert not any("lineSpacing" in p["style"] for p in requests(result, "updateParagraphStyle"))
    assert requests(result, "updateTextStyle")[0]["style"]["fontSize"]["magnitude"] == 12
