# Font measurements

Numbers only (units per em, line metrics and each character's advance width),
extracted by `scripts/font_metrics.py` for `publisher_fit.py` to lay text out
in the font Google Slides draws with. No font file ships with the app.

| File | From |
|---|---|
| `andika.json` | Andika 6.101, as served by Google Fonts (github.com/google/fonts, `ofl/andika`). Copyright SIL International. The font is licensed under the SIL Open Font License 1.1. |
| `calibri.json` | Carlito 1.104, metric-compatible with Calibri (the same advance widths by design), from Debian `fonts-crosextra-carlito` 20230309-2. Carlito is licensed under the SIL Open Font License 1.1. Slides draws Calibri itself; these are its widths. |
| `arial.json` | Liberation Sans 2.1.5, metric-compatible with Arial, from Debian `fonts-liberation` 1:2.1.5-3. Licensed under the SIL Open Font License 1.1. Slides draws Arial, and draws a font it doesn't have in Arial. |
