import asyncio
import json
import zipfile
from dataclasses import replace

import pytest
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.jobs import preflight, workspace
from workspace_toolkit.package import PPTX_MIME, Package, validate_upload_name
from workspace_toolkit.pptx import NS, analyse

from .conftest import fixture_parts, write_pptx


def test_manifest_order_geometry_media_and_risks(pptx, tmp_path):
    before = pptx.read_bytes()
    manifest = analyse(pptx, tmp_path / "out")
    assert [p["sourcePart"] for p in manifest["pages"]] == [
        "ppt/slides/slide2.xml",
        "ppt/slides/slide1.xml",
    ]
    assert manifest["document"] == {"pageCount": 2, "widthPt": 840, "heightPt": 595}
    text = manifest["pages"][0]["elements"][0]
    assert text["bounds"] == {"x": 1, "y": 2, "width": 10, "height": 20}
    assert text["rotation"] == 90
    assert text["paragraphs"][0]["runs"][0]["text"] == "Hello school"
    assert {a["kind"] for a in manifest["assets"].values()} == {"image", "audio", "video"}
    assert len(manifest["assets"]) == 3  # duplicate image payload is deduplicated
    assert {f["name"] for f in manifest["fonts"]} == {"Calibri"}
    assert manifest["declaredFonts"] == ["Aptos"]
    assert text["paragraphs"][0]["runs"][0]["sourceStyle"]["fontFamily"] == "Calibri"
    assert "" not in manifest["relationships"]
    assert "_package" in manifest["relationships"]
    assert {w["code"] for w in manifest["warnings"]} >= {
        "timing",
        "transition",
        "external_link",
        "embedded_asset",
    }
    unknown = manifest["pages"][0]["elements"][-1]
    assert unknown["type"] == "unknown" and unknown["classification"] == "UNSUPPORTED"
    assert pptx.read_bytes() == before
    assert len(list((tmp_path / "out/assets").iterdir())) == 3
    assert "Hello school" not in (tmp_path / "out/report.json").read_text()


def test_ordinary_shape_with_empty_text_body_stays_a_shape(tmp_path):
    parts = fixture_parts()
    parts["ppt/slides/slide1.xml"] = (
        f'''<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvSpPr/></p:nvSpPr><p:spPr/><p:txBody><a:p/></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'''
    )
    path = write_pptx(tmp_path / "shape.pptx", parts)
    manifest = analyse(path, tmp_path / "out")
    assert manifest["pages"][1]["elements"][0]["type"] == "shape"


def test_repeat_is_deterministic(pptx, tmp_path):
    first = analyse(pptx, tmp_path / "one")
    second = analyse(pptx, tmp_path / "two")
    assert first == second


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "C:/escape", "ppt/../escape", "ppt\\escape"]
)
def test_archive_traversal_rejected(tmp_path, name):
    parts = fixture_parts()
    parts[name.replace("\\", "/")] = b"bad"
    path = write_pptx(tmp_path / "unsafe.pptx", parts)
    if "\\" in name:
        path.write_bytes(path.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
    with pytest.raises(ToolkitError, match="unsafe package"):
        Package(path, Settings())
    assert not (tmp_path / "escape").exists()


def test_duplicate_paths_rejected(pptx):
    with zipfile.ZipFile(pptx, "a") as z:
        z.writestr("PPT/PRESENTATION.XML", "bad")
    with pytest.raises(ToolkitError, match="unsafe package"):
        Package(pptx, Settings())


@pytest.mark.parametrize(
    "change, code",
    [
        ({"max_entries": 2}, "zip_entries"),
        ({"max_entry_bytes": 20}, "zip_limits"),
        ({"max_expanded_bytes": 50}, "zip_limits"),
        ({"max_compression_ratio": 1}, "zip_limits"),
        ({"max_xml_bytes": 20}, "part_limit"),
        ({"max_upload_bytes": 2}, "upload_too_large"),
    ],
)
def test_processing_limits(pptx, change, code):
    with pytest.raises(ToolkitError) as error:
        Package(pptx, replace(Settings(), **change))
    assert error.value.code == code


def test_external_entities_rejected(tmp_path):
    parts = fixture_parts()
    parts["ppt/presentation.xml"] = (
        '<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><x>&leak;</x>'
    )
    path = write_pptx(tmp_path / "entity.pptx", parts)
    with pytest.raises(ToolkitError, match="unsafe or damaged"):
        analyse(path, tmp_path / "out")


def test_macros_rejected(tmp_path):
    parts = fixture_parts()
    parts["ppt/vbaProject.bin"] = b"unexecuted"
    with pytest.raises(ToolkitError, match="macros"):
        Package(write_pptx(tmp_path / "macro.pptx", parts), Settings())


def test_relationship_escape_rejected(tmp_path):
    parts = fixture_parts()
    parts["ppt/_rels/presentation.xml.rels"] = parts["ppt/_rels/presentation.xml.rels"].replace(
        "slides/slide1.xml", "../../outside"
    )
    with pytest.raises(ToolkitError, match="unsafe component"):
        analyse(write_pptx(tmp_path / "bad.pptx", parts), tmp_path / "out")


@pytest.mark.parametrize(
    "filename,mime", [("../x.pptx", PPTX_MIME), ("x.pptm", PPTX_MIME), ("x.pptx", "text/html")]
)
def test_upload_metadata(filename, mime):
    with pytest.raises(ToolkitError):
        validate_upload_name(filename, mime)


def test_wrong_signature(tmp_path):
    path = tmp_path / "x.pptx"
    path.write_bytes(b"not a zip")
    with pytest.raises(ToolkitError, match="valid .pptx"):
        Package(path, Settings())


def test_worker_and_cleanup(pptx, tmp_path):
    settings = replace(Settings(), temp_dir=str(tmp_path))
    with workspace(settings) as (_, root):
        (root / "source.pptx").write_bytes(pptx.read_bytes())
        result = asyncio.run(preflight(root, settings))
        assert result["document"]["pageCount"] == 2
        assert json.loads((root / "result/report.json").read_text())["status"] == "analysed"
    assert not root.exists()


def test_cleanup_on_failure(tmp_path):
    settings = replace(Settings(), temp_dir=str(tmp_path))
    with pytest.raises(ToolkitError), workspace(settings) as (_, root):
        (root / "source.pptx").write_bytes(b"bad")
        asyncio.run(preflight(root, settings))
    assert not root.exists()
