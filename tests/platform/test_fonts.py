import json
import zipfile

from workspace_toolkit.config import Settings
from workspace_toolkit.fonts import FontStatus, catalogue, compatibility
from workspace_toolkit.pptx import render_path

from .conftest import fixture_parts, write_pptx


def test_metric_compatible_office_families_have_reviewed_replacements():
    expected = {
        "Calibri": "Carlito",
        "Cambria": "Caladea",
        "Arial": "Arimo",
        "Times New Roman": "Tinos",
        "Courier New": "Cousine",
    }
    for source, replacement in expected.items():
        result = compatibility(source)
        assert result["status"] == FontStatus.SUBSTITUTED
        assert result["replacement"] == replacement
        assert result["metricCompatible"] is True
        assert result["confidence"] == "high"


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
    assert compatibility("Comic Sans MS")["replacement"] == "Comic Neue"
    assert compatibility("Chalkduster")["replacement"] == "Schoolbell"


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
    assert b'typeface="Carlito"' in slide
    assert b'typeface="Carlito"' in theme
    assert b'typeface="OpenDyslexic"' in accessibility
    assert report["fontSubstitutions"] == [
        {
            "original": "Aptos",
            "replacement": "Carlito",
            "occurrences": 1,
            "classification": "SUBSTITUTED",
        },
        {
            "original": "Calibri",
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
    assert {item["original"] for item in report["fontSubstitutions"]} == {
        "Aptos",
        "Calibri",
    }
