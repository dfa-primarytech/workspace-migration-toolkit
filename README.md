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
| Floating / anchored text boxes | **Floating tables positioned at the original coordinates**, preserving text, inline images and the shape's fill colour as cell shading |
| Text boxes stacked on a backing picture | The text box alone — the backing image is dropped (see below) |
| Floating pictures | Left as floating anchors, so Docs imports them with its own wrap/position controls |
| Charts, SmartArt, grouped shapes, drawing canvases and anything else unrecognised | Preserved untouched for Google's importer, and **reported back to the user** so they know to check them |
| Legacy VML-only pictures | Modern inline DrawingML pictures |
| Handwritten "ink" annotations | Removed |
| `mc:Fallback` branches | Discarded; `mc:Choice` is promoted |
| Full-page decorative backgrounds in headers/footers | Removed, detected by size + page-aspect match so real letterhead logos survive |

### Layout preservation

Google Docs supports floating tables, and its `.docx` importer honours OOXML
floating-table positioning (`w:tblpPr`) — verified with a probe document. So a
text box becomes a table carrying the anchor's **actual coordinates**: editable
text *and* original position, rather than a trade between them.

The mapping is direct:

| Anchor | Table |
|---|---|
| `posOffset` (EMU) | `tblpX` / `tblpY` (÷ 635 → dxa) |
| `relativeFrom="column\|paragraph"` | `horzAnchor`/`vertAnchor="text"` |
| `relativeFrom="margin"` (any variant) | `"margin"` |
| `relativeFrom="page"` | `"page"` |
| `wp:align` keyword | `tblpXSpec` / `tblpYSpec` |
| `distL`/`distR`/`distT`/`distB` | `leftFromText` etc. |

A text box with no usable position still produces a valid inline table.

Setting `FLOAT_TEXTBOX_TABLES = false` restores the previous approach, which
approximated layout by grouping anchors per paragraph, sorting them
top-to-bottom then left-to-right, and merging same-row anchors into multi-cell
table rows. Kept as a fallback.

### Backing pictures

Word builds "card" layouts by stacking a text box on a picture of identical size
and position. Inline content can't overlap, so emitting both tears the card in
half and doubles the document's length. The converter detects coincident pairs
(within 0.06" and 3% size) and drops the picture, keeping the text editable.

In testing, 2 of 4 documents used this pattern for *every* text box.

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
| `FLOAT_TEXTBOX_TABLES` | `true` | Emit each text box as a floating table at its original coordinates. `false` falls back to inline tables ordered by position. |
| `KEEP_BACKING_PICTURES` | `false` | Keep the artwork under a text box instead of dropping it. Only meaningful when text boxes float; z-ordering unverified. |
| `KEEP_PICTURES_FLOATING` | `true` | Leave pictures as floating anchors so they stay draggable in Docs. Set `false` to force everything inline. |
| `COINCIDENT_TOL_EMU` | 0.06" | Position tolerance for backing-picture detection |
| `COINCIDENT_SIZE_TOL` | 0.03 | Size tolerance for the same |
| `ROW_TOL_EMU` | 0.35" | Vertical distance within which anchors count as one visual row |

## Known limitations

- **Backing pictures are still dropped by default.** Now that text boxes float,
  a card's artwork could be kept underneath it — but the importer's z-ordering
  between a floating table and a floating picture is unverified, and getting it
  wrong hides the text. Set `KEEP_BACKING_PICTURES = true` to try it.
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
