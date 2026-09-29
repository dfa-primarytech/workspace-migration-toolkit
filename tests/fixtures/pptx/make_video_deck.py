"""Builds video-deck.pptx, the fixture for embedded-video tests (issue #36).

Synthetic: python-pptx's own default template, two slides of made-up text, a
generated poster image and a stand-in video of arbitrary bytes. No real
document or media is involved. python-pptx inserts a movie the way PowerPoint
does -- a p:pic with a:videoFile, a p14:media extension, a poster frame and a
p:video timing node -- and the template gives the deck the master, layouts and
theme a real deck has, which the hand-written test packages do not.

Regenerate (needs python-pptx, which is deliberately not a project dependency):

    python tests/fixtures/pptx/make_video_deck.py
"""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

HERE = Path(__file__).parent


def png(width: int, height: int) -> bytes:
    """A plain grey PNG, written by hand so no imaging library is needed."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    deck = Presentation()
    first = deck.slides.add_slide(deck.slide_layouts[5])  # title only
    first.shapes.title.text = "Volcanoes"
    movie = first.shapes.add_movie(
        io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 256),
        Inches(1),
        Inches(2),
        Inches(6),
        Inches(3.375),
        poster_frame_image=io.BytesIO(png(64, 36)),
        mime_type="video/mp4",
    )
    movie.name = "Volcano eruption"
    second = deck.slides.add_slide(deck.slide_layouts[1])  # title and content
    second.shapes.title.text = "Hello school"
    second.placeholders[1].text = "What happens after an eruption?"
    deck.save(HERE / "video-deck.pptx")


if __name__ == "__main__":
    main()
