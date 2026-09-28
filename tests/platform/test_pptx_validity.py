"""Does LibreOffice accept a deck after its video has been taken out?

Every test in test_pptx_video.py reads the result back with our own code. This
asks an independent OOXML implementation instead: LibreOffice Impress opens the
stripped deck and lays out its slides, and the text on them reaches the page.
That says the package is sound. It says nothing about how Google lays it out.

Requires `soffice` (Impress) and `pdftotext`. Skips when absent so local runs
stay fast; CI installs both, and fails the job if anything here is skipped.
"""

from __future__ import annotations

import zipfile

from workspace_toolkit.config import Settings
from workspace_toolkit.pptx import render_path

from .test_docx_validity import needs_pdftotext, rendered_page_texts, soffice_convert
from .test_pptx_video import video_deck


@needs_pdftotext
def test_libreoffice_opens_a_deck_whose_video_was_taken_out(tmp_path):
    source = video_deck(tmp_path)
    converted = tmp_path / "converted.pptx"
    report = render_path(source, converted, Settings())
    assert report["videosRemoved"], "the check is only meaningful if a video went"
    assert not any(n.endswith(".mp4") for n in zipfile.ZipFile(converted).namelist())

    pdf = soffice_convert(converted, "pdf", tmp_path / "pdf")
    pages = rendered_page_texts(pdf)
    # The fixture's two slides; slide 2 carries text. A blank-page PDF would
    # mean LibreOffice gave up on the deck rather than drew it.
    assert len(pages) == 2, f"expected 2 slides, got {len(pages)}"
    assert any("Hello school" in page for page in pages)
