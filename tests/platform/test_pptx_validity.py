"""Does LibreOffice accept a deck after its video has been taken out?

Every test in test_pptx_video.py reads the result back with our own code. This
asks an independent OOXML implementation instead: LibreOffice Impress opens the
deck and lays out its slides, and the text on them reaches the page. That says
the package is sound. It says nothing about how Google lays it out.

The deck is `tests/fixtures/pptx/video-deck.pptx`, built by python-pptx from a
real PowerPoint template (see make_video_deck.py): it has the master, layouts
and theme a real deck has, which the hand-written test packages do not. The
untouched deck is converted first, as a control -- so a failure afterwards is
the stripping's, not the fixture's.

Requires `soffice` (Impress) and `pdftotext`. Skips when absent so local runs
stay fast; CI installs both, and fails the job if anything here is skipped.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from workspace_toolkit.config import Settings
from workspace_toolkit.pptx import render_path

from .test_docx_validity import needs_pdftotext, rendered_page_texts, soffice_convert

DECK = Path(__file__).parents[1] / "fixtures" / "pptx" / "video-deck.pptx"


def slide_texts(deck: Path, outdir: Path) -> list[str]:
    return rendered_page_texts(soffice_convert(deck, "pdf", outdir))


@needs_pdftotext
def test_libreoffice_opens_a_deck_whose_video_was_taken_out(tmp_path):
    source = tmp_path / "source.pptx"
    shutil.copyfile(DECK, source)

    control = slide_texts(source, tmp_path / "control")
    assert len(control) == 2, f"control: LibreOffice laid out {len(control)} slides, not 2"
    assert "Volcanoes" in control[0] and "Hello school" in control[1], control

    converted = tmp_path / "converted.pptx"
    report = render_path(source, converted, Settings())
    assert report["videosRemoved"], "the check is only meaningful if a video went"
    assert not any(n.endswith(".mp4") for n in zipfile.ZipFile(converted).namelist())

    stripped = slide_texts(converted, tmp_path / "stripped")
    assert len(stripped) == 2, f"stripped: LibreOffice laid out {len(stripped)} slides, not 2"
    assert "Volcanoes" in stripped[0] and "Hello school" in stripped[1], stripped
