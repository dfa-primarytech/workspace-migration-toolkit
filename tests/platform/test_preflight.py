import asyncio
import json
import os
import sys
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
    assert manifest["fonts"] == [
        {
            "name": "Calibri",
            # Measured as present in Google Docs on 2026-09-23, so it is left
            # alone. This entry previously claimed Calibri had to become
            # Carlito, which cost the author's choice for no gain.
            "status": "AVAILABLE",
            "replacement": None,
            "confidence": "high",
            "basis": "measured-present-in-google-docs",
            "workspaceAvailability": "measured-2026-09-23",
            "manualReview": False,
        }
    ]
    assert manifest["declaredFontCompatibility"][0]["replacement"] == "Carlito"
    assert manifest["declaredFonts"] == ["Aptos"]
    assert {font["name"] for font in manifest["fontRequirements"]} == {"Aptos", "Calibri"}
    assert text["paragraphs"][0]["runs"][0]["sourceStyle"]["fontFamily"] == "Calibri"
    # Calibri needs no replacement: Google Docs has it. The run keeps the font
    # the author chose, and the report says so rather than proposing a swap.
    assert (
        text["paragraphs"][0]["runs"][0]["sourceStyle"]["fontCompatibility"]["replacement"] is None
    )
    assert (
        text["paragraphs"][0]["runs"][0]["sourceStyle"]["fontCompatibility"]["status"]
        == "AVAILABLE"
    )
    assert "" not in manifest["relationships"]
    assert "_package" in manifest["relationships"]
    assert {w["code"] for w in manifest["warnings"]} >= {
        "timing",
        "transition",
        "external_link",
        "embedded_asset",
        "font_substitution",
    }
    assert {
        warning["font"]
        for warning in manifest["warnings"]
        if warning["code"] == "font_substitution"
    } == {"Aptos"}  # Calibri is present in Docs, so there is nothing to warn about
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
        # The floors, with the in-proportion allowance switched off.
        ({"max_entry_bytes": 20, "entry_scale": 0}, "zip_limits"),
        ({"max_expanded_bytes": 50, "expanded_scale": 0}, "zip_limits"),
        ({"max_compression_ratio": 1}, "zip_limits"),
        ({"max_xml_bytes": 20}, "part_limit"),
        ({"max_xml_elements": 2}, "xml_limit"),
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


def test_a_link_to_a_missing_part_is_reported_not_fatal(tmp_path):
    """Issue #47: some generators write Target="../NULL" for a removed picture.

    PowerPoint opens those files, so refusing the whole presentation over one
    dead link is worse than useless. It is read, and the link is reported.
    """
    parts = fixture_parts()
    rels = "ppt/slides/_rels/slide2.xml.rels"
    parts[rels] = parts[rels].replace(
        "</Relationships>",
        f'<Relationship Id="dead" Type="{NS["r"]}/image" Target="../NULL"/></Relationships>',
    )
    manifest = analyse(write_pptx(tmp_path / "null.pptx", parts), tmp_path / "out")
    missing = [w for w in manifest["warnings"] if w["code"] == "relationship_target_missing"]
    assert [(w["part"], w["relationshipId"]) for w in missing] == [
        ("ppt/slides/slide2.xml", "dead")
    ]
    assert len(manifest["pages"]) == 2


def test_a_missing_slide_is_still_refused(tmp_path):
    # A dead picture link loses a picture; a dead slide link loses the order
    # of the whole deck, so that one stays fatal.
    parts = fixture_parts()
    del parts["ppt/slides/slide1.xml"]
    with pytest.raises(ToolkitError) as error:
        analyse(write_pptx(tmp_path / "noslide.pptx", parts), tmp_path / "out")
    assert error.value.code == "invalid_slide_order"


def test_links_resolve_case_insensitively(tmp_path):
    # OPC part names are case-insensitive; Office follows "Slide1.XML".
    parts = fixture_parts()
    rels = "ppt/_rels/presentation.xml.rels"
    parts[rels] = parts[rels].replace("slides/slide1.xml", "Slides/Slide1.XML")
    manifest = analyse(write_pptx(tmp_path / "case.pptx", parts), tmp_path / "out")
    assert manifest["pages"][1]["sourcePart"] == "ppt/slides/slide1.xml"
    assert not [w for w in manifest["warnings"] if w["code"] == "relationship_target_missing"]


@pytest.mark.parametrize(
    "filename,mime",
    [
        ("../x.pptx", PPTX_MIME),
        ("x.pptm", PPTX_MIME),
        ("x.pptx", "text/html"),
        ("bad\tname.pptx", PPTX_MIME),
    ],
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


def test_a_cancelled_preflight_stops_the_worker_and_stays_cancelled(pptx, tmp_path, monkeypatch):
    # Issue #52: cancellation was reported as "took too long to analyse", so
    # the job timeout and a client disconnect both lost their real cause.
    settings = replace(Settings(), temp_dir=str(tmp_path))
    spawned = []
    real_exec = asyncio.create_subprocess_exec

    async def slow_worker(*args, **kwargs):
        process = await real_exec(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr("workspace_toolkit.jobs.asyncio.create_subprocess_exec", slow_worker)

    async def cancel_it(root):
        task = asyncio.create_task(preflight(root, settings))
        while not spawned:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with workspace(settings) as (_, root):
        (root / "source.pptx").write_bytes(pptx.read_bytes())
        asyncio.run(cancel_it(root))
    assert spawned[0].returncode is not None, "the worker was left running"


def test_the_job_timeout_is_not_reported_as_a_parser_timeout(pptx, tmp_path, monkeypatch):
    settings = replace(Settings(), temp_dir=str(tmp_path))
    real_exec = asyncio.create_subprocess_exec

    async def slow_worker(*args, **kwargs):
        return await real_exec(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)

    monkeypatch.setattr("workspace_toolkit.jobs.asyncio.create_subprocess_exec", slow_worker)

    async def run(root):
        async with asyncio.timeout(0.5):
            await preflight(root, settings)

    with workspace(settings) as (_, root):
        (root / "source.pptx").write_bytes(pptx.read_bytes())
        with pytest.raises(TimeoutError):
            asyncio.run(run(root))


GROUPED = (
    "<p:grpSp><p:nvGrpSpPr/><p:grpSpPr><a:xfrm>"
    "<a:off x='1270000' y='2540000'/><a:ext cx='2540000' cy='1270000'/>"
    "<a:chOff x='0' y='0'/><a:chExt cx='1270000' cy='1270000'/>"
    "</a:xfrm></p:grpSpPr>"
    "<p:sp><p:spPr><a:xfrm><a:off x='635000' y='0'/><a:ext cx='635000' cy='635000'/>"
    "</a:xfrm></p:spPr></p:sp>"
    "<p:grpSp><p:nvGrpSpPr/><p:grpSpPr><a:xfrm>"
    "<a:off x='0' y='635000'/><a:ext cx='635000' cy='635000'/>"
    "<a:chOff x='1270000' y='1270000'/><a:chExt cx='1270000' cy='1270000'/>"
    "</a:xfrm></p:grpSpPr>"
    "<p:sp><p:spPr><a:xfrm><a:off x='1270000' y='1270000'/><a:ext cx='1270000' cy='1270000'/>"
    "</a:xfrm></p:spPr></p:sp>"
    "</p:grpSp></p:grpSp>"
)


def test_group_children_are_placed_in_slide_coordinates(tmp_path):
    # Issue #52: a child's a:off / a:ext are in its group's chOff / chExt
    # space, and were reported as if they were slide points.
    parts = fixture_parts()
    parts["ppt/slides/slide1.xml"] = (
        f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree>'
        f"{GROUPED}</p:spTree></p:cSld></p:sld>"
    )
    source = write_pptx(tmp_path / "grouped.pptx", parts)
    manifest = analyse(source, tmp_path / "out")
    slide = next(p for p in manifest["pages"] if p["index"] == 1)
    bounds = [e["bounds"] for e in slide["elements"]]
    # Outer group: 200 x 100 pt at (100, 200), child space 100 x 100, so x
    # doubles. Its shape: x 50 -> 200, width 50 -> 100.
    assert bounds[0] == {"x": 100.0, "y": 200.0, "width": 200.0, "height": 100.0}
    assert bounds[1] == {"x": 200.0, "y": 200.0, "width": 100.0, "height": 50.0}
    # Inner group sits at (0, 50) in the outer space -> (100, 250) on the slide,
    # 50 x 50 there -> 100 x 50; its child fills it.
    assert bounds[2] == {"x": 100.0, "y": 250.0, "width": 100.0, "height": 50.0}
    assert bounds[3] == {"x": 100.0, "y": 250.0, "width": 100.0, "height": 50.0}


# ------------------------------------------------ no fixed size limit (#36)


def test_there_is_no_upload_limit_by_default():
    assert Settings().max_upload_bytes is None


def test_a_large_part_is_allowed_in_proportion_to_a_large_file(tmp_path):
    # Real media barely compresses: a part about the size of the whole file
    # is normal, and was refused whenever it passed the fixed 50 MiB.
    parts = fixture_parts()
    parts["ppt/media/video.mp4"] = os.urandom(200_000)
    path = write_pptx(tmp_path / "big.pptx", parts)
    tight = replace(Settings(), max_entry_bytes=1000, max_expanded_bytes=1000)
    Package(path, tight).close()  # does not raise


def test_a_small_file_that_expands_hugely_is_still_refused(tmp_path):
    # The allowance is in proportion to the file, so a zip bomb -- tiny on
    # disk, enormous expanded -- meets the floor exactly as before.
    parts = fixture_parts()
    parts["ppt/media/video.mp4"] = bytes(5_000_000)
    path = write_pptx(tmp_path / "bomb.pptx", parts)
    settings = replace(Settings(), max_entry_bytes=1_000_000, max_compression_ratio=10**9)
    with pytest.raises(ToolkitError) as error:
        Package(path, settings)
    assert error.value.code == "zip_limits"


def test_time_and_memory_allowances_grow_with_the_file():
    settings = Settings()
    mib = 1024 * 1024
    assert settings.parser_timeout_for(0) == 30
    assert settings.parser_timeout_for(400 * mib) == 130
    assert settings.job_timeout_for(0) == 240
    assert settings.job_timeout_for(100 * mib) == 440
    assert settings.job_timeout_for(10_000 * mib) == 3300, "stays under Cloud Run's hour"
    assert settings.worker_memory_for(300 * mib) == 1368 * mib


def test_max_upload_size_is_optional(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_SIZE", raising=False)
    assert Settings.from_env().max_upload_bytes is None
    monkeypatch.setenv("MAX_UPLOAD_SIZE", str(500 * 1024 * 1024))
    assert Settings.from_env().max_upload_bytes == 500 * 1024 * 1024
    monkeypatch.setenv("MAX_UPLOAD_SIZE", "0")
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.skipif(sys.platform == "win32", reason="OS resource limits are Linux-only")
def test_a_worker_under_a_stricter_inherited_limit_still_runs(pptx, tmp_path):
    # A process cannot raise a hard limit it inherited. The worker's memory cap
    # grows with the file, so it must settle for the stricter cap, not fail.
    import resource
    import subprocess

    output = tmp_path / "result"
    output.mkdir()
    config = tmp_path / "limits.json"
    config.write_text("{}", encoding="utf-8")
    ceiling = 700 * 1024 * 1024  # below the worker's own 768 MiB

    def tighter():
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))

    run = subprocess.run(  # noqa: S603 -- fixed argv
        [
            sys.executable,
            "-m",
            "workspace_toolkit.worker",
            str(pptx),
            str(output),
            str(config),
            "pptx",
        ],
        preexec_fn=tighter,  # noqa: PLW1509 -- test-only, no threads
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert run.returncode == 0, (
        (output / "error.json").read_text() if (output / "error.json").exists() else run.stderr
    )
