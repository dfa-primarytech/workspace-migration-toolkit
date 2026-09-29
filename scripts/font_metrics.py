"""Extracts the measurements text fitting needs from a font family's files.

    pip install fonttools
    python scripts/font_metrics.py andika path/to/Andika-{Regular,Bold,Italic,BoldItalic}.ttf

Writes app/workspace_toolkit/font_metrics/<name>.json: units per em, the
vertical metrics a browser lays lines out with, and each character's advance
width for Latin text and common punctuation. Only numbers are kept, never
glyph outlines, so no font file ships with the app. Kerning is left out: it
moves a line by a fraction of a character, and the fit keeps a margin.

Use the files Google Fonts serves (github.com/google/fonts), so the numbers
are those of the font Google Slides draws with.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

RANGES = [
    (0x0020, 0x024F),  # Basic Latin, Latin-1, Latin Extended A and B
    (0x02B0, 0x02FF),  # spacing modifiers
    (0x2000, 0x206F),  # general punctuation: dashes, quotes, bullets, spaces
    (0x20A0, 0x20CF),  # currency
    (0x2100, 0x214F),  # letterlike symbols
]
STYLES = ("regular", "bold", "italic", "boldItalic")


def widths(font: TTFont) -> dict[str, int]:
    cmap = font.getBestCmap()
    advances = font["hmtx"].metrics
    result = {}
    for start, end in RANGES:
        for code in range(start, end + 1):
            glyph = cmap.get(code)
            if glyph is not None:
                result[str(code)] = advances[glyph][0]
    return result


def main() -> None:
    name, *paths = sys.argv[1:]
    if len(paths) != len(STYLES):
        raise SystemExit("give the regular, bold, italic and bold italic files, in that order")
    fonts = [TTFont(path) for path in paths]
    first = fonts[0]
    hhea, os2 = first["hhea"], first["OS/2"]
    data = {
        "family": first["name"].getDebugName(1),
        "version": first["name"].getDebugName(5),
        "source": "Google Fonts (github.com/google/fonts), SIL Open Font License 1.1",
        "unitsPerEm": first["head"].unitsPerEm,
        # USE_TYPO_METRICS set means browsers take the typo values; Google
        # Fonts keeps hhea equal to them, so either reading gives these.
        "ascent": os2.sTypoAscender if os2.fsSelection & 128 else hhea.ascent,
        "descent": -(os2.sTypoDescender if os2.fsSelection & 128 else hhea.descent),
        "lineGap": os2.sTypoLineGap if os2.fsSelection & 128 else hhea.lineGap,
        "styles": {},
    }
    for style, font in zip(STYLES, fonts, strict=True):
        advances = widths(font)
        data["styles"][style] = {
            "average": round(sum(advances.values()) / len(advances)),
            "widths": advances,
        }
    out = Path(__file__).parents[1] / "app" / "workspace_toolkit" / "font_metrics" / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{out}: {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
