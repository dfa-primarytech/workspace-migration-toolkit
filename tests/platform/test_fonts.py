import json
import zipfile

from workspace_toolkit.config import Settings
from workspace_toolkit.fonts import FontStatus, catalogue, compatibility
from workspace_toolkit.pptx import render_path

from .conftest import fixture_parts, write_pptx


def test_the_families_google_docs_ships_are_left_alone():
    """Measured, not assumed: Docs has these, so replacing them is pure loss.

    This test previously asserted the opposite -- that Calibri became Carlito,
    Arial became Arimo and so on. That was built on the assumption that
    Microsoft's families are absent from Google Docs. Converting a document
    naming each one and reading back which fonts the renderer actually used
    showed the assumption is false for all of them.

    Substituting a family Docs already has costs the author's choice and buys
    nothing: the document arrives in a typeface nobody picked.
    """
    for family in (
        "Calibri",
        "Cambria",
        "Arial",
        "Times New Roman",
        "Courier New",
        "Century Gothic",
        "Georgia",
        "Garamond",
        "Comic Sans MS",
    ):
        result = compatibility(family)
        assert result["status"] == FontStatus.AVAILABLE, family
        assert result["replacement"] is None, (
            f"{family} is present in Google Docs but was given a replacement"
        )
        assert result["basis"] == "measured-present-in-google-docs"


def test_the_metric_compatible_families_remain_available_to_recommend():
    """Carlito and the rest are still real, still Google Fonts, still usable.

    Removing the mappings does not remove the families: something genuinely
    missing may still want a metric-compatible substitute.
    """
    for family in ("Carlito", "Caladea", "Arimo", "Tinos", "Cousine"):
        assert compatibility(family)["status"] == FontStatus.AVAILABLE, family


def test_google_candidate_is_preserved_but_workspace_availability_is_not_overclaimed():
    result = compatibility("  comic   neue ")
    assert result == {
        "name": "comic neue",
        "status": FontStatus.AVAILABLE,
        "replacement": "Comic Neue",
        "confidence": "high",
        "basis": "curated-google-fonts-catalogue",
        "workspaceAvailability": "unverified",
        "manualReview": False,
    }


def test_education_families_keep_their_intent_in_the_reason():
    assert compatibility("Sassoon Primary")["replacement"] == "Andika"
    assert "literacy" in str(compatibility("Sassoon Primary")["reason"])
    # Comic Sans MS was here until it was measured as present in Docs; a
    # family Google ships needs no education-minded replacement.
    assert compatibility("Comic Sans MS")["replacement"] is None
    assert compatibility("Chalkduster")["replacement"] == "Schoolbell"
    assert compatibility("Twinkl")["replacement"] == "Andika"


def test_accessibility_mapping_always_requires_review():
    result = compatibility("OpenDyslexic")
    assert result["replacement"] == "Lexend"
    assert result["confidence"] == "low"
    assert result["manualReview"] is True
    assert "not a like-for-like" in str(result["reason"])


def test_unknown_font_never_silently_falls_back():
    result = compatibility("School Custom Display 2026")
    assert result["status"] == FontStatus.UNKNOWN
    assert result["replacement"] is None
    assert result["manualReview"] is True


def test_catalogue_is_deduplicated_and_deterministic():
    result = catalogue([" Calibri ", "calibri", "Z Custom", "Arial"])
    assert [font["name"] for font in result] == ["Arial", "Calibri", "Z Custom"]


def test_pptx_renderer_applies_reviewed_candidates_without_changing_source(tmp_path):
    parts = fixture_parts()
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(
        "<a:t>Last slide</a:t>",
        '<a:rPr><a:latin typeface="OpenDyslexic"/></a:rPr><a:t>Last slide</a:t>',
    )
    source = write_pptx(tmp_path / "source.pptx", parts)
    before = source.read_bytes()
    destination = tmp_path / "converted.pptx"

    report = render_path(source, destination, Settings())

    assert source.read_bytes() == before
    with zipfile.ZipFile(destination) as package:
        slide = package.read("ppt/slides/slide2.xml")
        theme = package.read("ppt/theme/theme1.xml")
        accessibility = package.read("ppt/slides/slide1.xml")
    # Aptos is genuinely absent from Google Docs, so it is replaced.
    assert b'typeface="Carlito"' in theme
    # Calibri is not. It used to be replaced here too, until converting a
    # document that named it showed Docs renders Calibri as Calibri. Swapping
    # it cost the author's choice and gained nothing.
    assert b'typeface="Calibri"' in slide, "a family Google Docs ships was replaced"
    # Accessibility families are never touched automatically, whatever else changes.
    assert b'typeface="OpenDyslexic"' in accessibility
    assert report["fontSubstitutions"] == [
        {
            "original": "Aptos",
            "replacement": "Carlito",
            "occurrences": 1,
            "classification": "SUBSTITUTED",
        },
    ]


def test_worker_writes_pptx_font_report(pptx, tmp_path, monkeypatch):
    from workspace_toolkit import worker

    output = tmp_path / "result"
    output.mkdir()
    config = tmp_path / "limits.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["worker", str(pptx), str(output), str(config), "pptx"])
    worker.main()

    assert (output / "converted.pptx").exists()
    report = json.loads((output / "render.json").read_text(encoding="utf-8"))
    # Calibri was in this set until it was measured as present in Google Docs.
    # Only families Docs genuinely lacks are replaced.
    assert {item["original"] for item in report["fontSubstitutions"]} == {"Aptos"}


def render_slide(tmp_path, slide_body):
    """Renders the fixture with slide 1's text body replaced; returns slide 1."""
    parts = fixture_parts()
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(
        "<a:p><a:r><a:t>Last slide</a:t></a:r></a:p>", slide_body
    )
    source = write_pptx(tmp_path / "source.pptx", parts)
    report = render_path(source, tmp_path / "converted.pptx", Settings())
    with zipfile.ZipFile(tmp_path / "converted.pptx") as package:
        return package.read("ppt/slides/slide1.xml").decode(), report


def test_only_the_latin_slot_is_substituted(tmp_path):
    # Issue #50: the candidates are Latin faces. An East Asian, complex-script,
    # symbol or bullet slot naming the same family keeps it.
    slide, _ = render_slide(
        tmp_path,
        '<a:p><a:pPr><a:buFont typeface="Aptos"/></a:pPr><a:r><a:rPr>'
        '<a:latin typeface="Aptos"/><a:ea typeface="Aptos"/><a:cs typeface="Aptos"/>'
        '<a:sym typeface="Aptos"/></a:rPr><a:t>x</a:t></a:r></a:p>',
    )
    assert '<a:latin typeface="Carlito"' in slide
    for slot in ("ea", "cs", "sym", "buFont"):
        assert f'<a:{slot} typeface="Aptos"' in slide, f"the {slot} slot was substituted"


def test_slide_text_that_looks_like_markup_is_never_rewritten(tmp_path):
    # A `"` needs no escaping in text, so this is exactly what a lesson on
    # HTML or CSS contains. It is content, not a font declaration.
    slide, report = render_slide(
        tmp_path, '<a:p><a:r><a:t>Set typeface="Aptos" in the style</a:t></a:r></a:p>'
    )
    assert 'typeface="Aptos" in the style' in slide
    assert report["fontSubstitutions"][0]["occurrences"] == 1  # the theme's, only


def test_a_replaced_face_loses_the_original_faces_metadata(tmp_path):
    slide, _ = render_slide(
        tmp_path,
        '<a:p><a:r><a:rPr><a:latin typeface="Aptos" panose="020B0004020202020204" '
        'pitchFamily="34" charset="0"/></a:rPr><a:t>x</a:t></a:r></a:p>',
    )
    assert '<a:latin typeface="Carlito"/>' in slide


def test_a_symbol_charset_latin_slot_is_left_alone(tmp_path):
    slide, _ = render_slide(
        tmp_path,
        '<a:p><a:r><a:rPr><a:latin typeface="Aptos" charset="2"/></a:rPr><a:t>x</a:t></a:r></a:p>',
    )
    assert '<a:latin typeface="Aptos" charset="2"/>' in slide
