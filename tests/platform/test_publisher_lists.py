"""Publisher lists, as the patched libmspub passes them on (DECISIONS.md,
2026-09-29), become Slides lists: one per run of the same kind of list."""

from __future__ import annotations

from workspace_toolkit.publisher_slides import KNOWN, list_requests, paragraph_style

WHERE = {"objectId": "box"}


def para(text: str, **props: object) -> tuple[dict, list[tuple[str, dict]]]:
    # librevenge_list_type= stands for the property librevenge:list-type
    names = {k.replace("_", ":", 1).replace("_", "-"): v for k, v in props.items()}
    return {"sourceProperties": names}, [(text, {})]


def numbered(text: str, **more: object) -> tuple[dict, list[tuple[str, dict]]]:
    return para(
        text,
        librevenge_list_type="ordered",
        librevenge_numbering_type="0",
        # libmspub's delimiter arrives in the value's upper half: 2 is "1."
        librevenge_numbering_delimiter=str(2 << 16),
        **more,
    )


def bulleted(text: str, codepoint: int = 0x2022) -> tuple[dict, list[tuple[str, dict]]]:
    return para(text, librevenge_list_type="unordered", librevenge_bullet_codepoint=str(codepoint))


def run(*items):
    paragraphs = [p for p, _ in items]
    laid = [pieces for _, pieces in items]
    return list_requests(WHERE, paragraphs, laid)


def ranges(requests: list[dict]) -> list[tuple[int, int, str]]:
    out = []
    for request in requests:
        body = request["createParagraphBullets"]
        span = body["textRange"]
        out.append((span["startIndex"], span["endIndex"], body["bulletPreset"]))
    return out


def test_consecutive_numbered_paragraphs_are_one_list():
    requests, notes = run(numbered("Look"), numbered("Say"), numbered("Read"))
    # "Look\nSay\nRead": one list over all three paragraphs, as "1."
    assert ranges(requests) == [(0, 13, "NUMBERED_DIGIT_ALPHA_ROMAN")]
    assert notes == []
    assert "createParagraphBullets" in KNOWN


def test_a_plain_paragraph_ends_a_list_and_the_next_starts_again():
    requests, _ = run(numbered("One"), para("Between"), numbered("Two"))
    assert ranges(requests) == [
        (0, 3, "NUMBERED_DIGIT_ALPHA_ROMAN"),
        (12, 15, "NUMBERED_DIGIT_ALPHA_ROMAN"),
    ]


def test_bullets_and_numbers_are_separate_lists():
    requests, _ = run(bulleted("Dot"), numbered("One"))
    assert [preset for *_, preset in ranges(requests)] == [
        "BULLET_DISC_CIRCLE_SQUARE",
        "NUMBERED_DIGIT_ALPHA_ROMAN",
    ]


def test_an_empty_paragraph_gets_no_bullet():
    requests, _ = run(bulleted("Dot"), bulleted(""), bulleted("Dot"))
    assert ranges(requests) == [
        (0, 3, "BULLET_DISC_CIRCLE_SQUARE"),
        (5, 8, "BULLET_DISC_CIRCLE_SQUARE"),
    ]


def test_what_slides_cannot_show_is_reported():
    _, notes = run(bulleted("Star", codepoint=0x2605))
    assert [n["code"] for n in notes] == ["list-bullet-dot"]

    _, notes = run(numbered("Later", text_start_value="4"))
    assert [n["code"] for n in notes] == ["list-restart"]

    unusual = para("i.", librevenge_list_type="ordered", librevenge_numbering_type="9")
    requests, notes = run(unusual)
    assert ranges(requests) == [(0, 2, "NUMBERED_DIGIT_ALPHA_ROMAN")]
    assert [n["code"] for n in notes] == ["list-numbers-digits"]


def test_a_paragraph_that_is_not_a_list_is_left_alone():
    requests, notes = run(para("Plain"), para("Text"))
    assert requests == [] and notes == []


def styled(**props: object) -> dict:
    paragraph, _ = para("Item", **props)
    style, _, _ = paragraph_style({**paragraph, "style": {"alignment": "center"}})
    return {k: v["magnitude"] for k, v in style.items() if k.startswith("indent")}


def test_a_list_items_indent_is_the_gap_from_bullet_to_text():
    # PUB-002 page 18: a 0.25 in margin and no hanging indent. Publisher sets
    # the bullet at the edge and the text at the margin; so must Slides.
    assert styled(librevenge_list_type="unordered", fo_margin_left="0.25in") == {
        "indentStart": 18.0,
        "indentFirstLine": 0.0,
    }
    # With no margin at all, the text still stands clear of its bullet.
    assert styled(librevenge_list_type="unordered")["indentStart"] > 0
    # A hanging indent the author set is kept as it is.
    hanging = styled(
        librevenge_list_type="unordered", fo_margin_left="0.5in", fo_text_indent="-0.25in"
    )
    assert hanging == {"indentStart": 36.0, "indentFirstLine": 18.0}
    # Not a list: a margin is a margin.
    assert styled(fo_margin_left="0.25in") == {"indentStart": 18.0, "indentFirstLine": 18.0}
