# workspace-migration-toolkit

Tools for migrating Microsoft Office documents to Google Workspace without the
formatting falling apart.

Built during a UK multi-academy trust's M365 → Google Workspace migration.
Currently one working tool, with research and plans for the rest:

| Tool | Format | Status |
|---|---|---|
| **docx-fixer** (below) | Word → Docs | **Working**, in production use |
| pptx media extractor | PowerPoint → Slides | Planned — [design](docs/research.md#powerpoint--google-slides) |
| xlsx estate analyser | Excel → Sheets | Planned — [design](docs/research.md#excel--google-sheets) |
| pub triage | Publisher → Slides/PDF | Planned — [⚠️ time-critical](docs/research.md#-time-critical-microsoft-publisher-retires-1-october-2026) |

---

## docx-fixer

Repair `.docx` files so they survive import into Google Docs.

Google's importer doesn't fail loudly on floating shapes — it quietly
reinterprets them. Text boxes become uneditable drawings, images land in the
wrong place, and legacy pictures vanish. This tool pre-processes the OOXML
*before* Drive ever sees it, rewriting the constructs Google can't handle into
ones it can.

It runs as a Google Apps Script web app: staff upload a `.docx`, and get back a
clean, editable Google Doc.

## Status

**Working, imperfect, in production use.** Built during a UK multi-academy
trust's migration from Microsoft 365 to Google Workspace, where staff-generated
worksheets — heavy with floating text boxes and images — were converting badly.

Output is substantially better than a raw Drive import, but not pixel-perfect.
See [Known limitations](#known-limitations).

## What it does

| Problem construct | Rewritten as |
|---|---|
| Floating / anchored text boxes | Inline 1×N tables, preserving text, inline images and the shape's fill colour as cell shading |
| Side-by-side text boxes | A single multi-cell table row, so two-column layouts stay two columns |
| Text boxes stacked on a backing picture | The text box alone — the backing image is dropped (see below) |
| Floating pictures | Left as floating anchors, so Docs imports them with its own wrap/position controls |
| Charts, SmartArt, grouped shapes, drawing canvases and anything else unrecognised | Preserved untouched for Google's importer, and **reported back to the user** so they know to check them |
| Legacy VML-only pictures | Modern inline DrawingML pictures |
| Handwritten "ink" annotations | Removed |
| `mc:Fallback` branches | Discarded; `mc:Choice` is promoted |
| Full-page decorative backgrounds in headers/footers | Removed, detected by size + page-aspect match so real letterhead logos survive |

### Layout preservation

Anchored objects carry a position; inline content doesn't. Rather than dumping
everything in XML order, the converter:

1. Groups anchors by their anchoring paragraph — vertical offsets are
   paragraph-relative, so they're only comparable within one group, and
   document order already carries the page-level flow.
2. Sorts each group top-to-bottom, then left-to-right.
3. Merges anchors sharing a visual row into one multi-cell table row.

On a sample of four real worksheets this reproduced two-column card layouts and
a full-width label sheet correctly.

### Backing pictures

Word builds "card" layouts by stacking a text box on a picture of identical size
and position. Inline content can't overlap, so emitting both tears the card in
half and doubles the document's length. The converter detects coincident pairs
(within 0.06" and 3% size) and drops the picture, keeping the text editable.

**Correction:** an earlier version of this note claimed 2 of 4 sample documents
used this pattern for every text box. That was wrong. Those "coincident
pictures" were anchors inside `mc:Fallback` — Word's legacy restatement of the
*same* text box — which the converter discards before it looks for backing
pictures. Measured properly, 6 of 18 anchors in one document and 4 of 15 in
another are fallback duplicates, and no sample contains a genuine backing
picture. The handling is still correct for documents that do use the pattern;
it simply does not fire on this sample.

## Install

1. Create a new Apps Script project at [script.google.com](https://script.google.com).
2. Add the three files from [`src/`](src/):
   - `Code.gs` — script file
   - `Index.html` — **HTML** file, named exactly `Index` (case-sensitive)
   - `appsscript.json` — enable via ⚙️ Project Settings → "Show `appsscript.json` manifest file in editor", then replace its contents
3. Confirm **Drive API v3** appears under Services.
4. **Deploy ▸ New deployment ▸ Web app.**

Or with [clasp](https://github.com/google/clasp): `clasp push` from `src/`.

## Configuration

Constants near the top of the anchor section in `src/Code.gs`:

| Constant | Default | Effect |
|---|---|---|
| `KEEP_PICTURES_FLOATING` | `true` | Leave pictures as floating anchors so they stay draggable in Docs. Set `false` to force everything inline. |
| `COINCIDENT_TOL_EMU` | 0.06" | Position tolerance for backing-picture detection |
| `COINCIDENT_SIZE_TOL` | 0.03 | Size tolerance for the same |
| `ROW_TOL_EMU` | 0.35" | Vertical distance within which anchors count as one visual row |

## Known limitations

- **Position is lost for text boxes.** They become inline tables stacked in
  reading order, so a laid-out page becomes a linear one.

  This is a limitation of the current implementation, not of Google Docs. Docs
  gained floating tables in 2023, and its `.docx` importer **does** honour
  OOXML floating-table positioning (`w:tblpPr`) — verified with a probe
  document: a table specified at `tblpX=7200`, `tblpY=2880` imported to exactly
  5in from the page left and 2in from the top, with text wrapping correctly.
  Emitting positioned tables instead of inline ones would preserve both the
  position and the editable text. Not yet implemented.
- **Only `word/document.xml` gets the structural passes.** Headers and footers
  get background-stripping only. Fine if your documents don't use them;
  a real gap if they do.
- **Untested against**: tracked changes, comments, footnotes, complex numbering,
  cross-references. The sample that drove development was image-heavy
  worksheets.
- **Apps Script limits** — 6-minute execution cap and in-memory DOM. Large
  documents may fail. Uploads over 25 MiB are rejected before browser reading
  and checked again on the server. This is a conservative policy, not a measured
  runtime limit; even smaller files can exceed it after ZIP expansion. The UI
  warns that files over 10 MiB may time out.
- Only PNG and JPEG are measured for background detection; EMF/WMF/GIF
  backgrounds are kept.
- **Charts, SmartArt, grouped shapes and canvases are preserved, not converted.**
  Google imports them as uneditable drawings. The conversion result lists how
  many were kept so they can be checked, but making them editable would mean
  recursing into groups — see issue #4.

## Roadmap

Expanding to the rest of the migration: PowerPoint, Excel and Publisher.
See [`docs/research.md`](docs/research.md) — including a **time-critical note on
Microsoft Publisher's retirement on 1 October 2026**.

## Contributing

Yes please — see [CONTRIBUTING.md](CONTRIBUTING.md). Sample files that convert
badly are as valuable as code.

## Licence

[MIT](LICENSE).
