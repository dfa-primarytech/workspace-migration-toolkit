# Migrating Microsoft Office documents to Google Workspace

Research notes from a UK multi-academy trust's M365 → Google Workspace
migration. Covers what breaks, what exists already, and what to build.

Last updated: September 2026.

---

## ⚠️ Time-critical: Microsoft Publisher retires 1 October 2026

Microsoft is ending Publisher support on **1 October 2026**. After that date,
Microsoft 365 subscribers can **no longer open or edit `.pub` files in Publisher
at all** — the app is removed from the suite, not merely unsupported. Only
perpetual-licence installs continue to work.

**If you have `.pub` files and anyone still has Publisher installed, batch-export
them now, while the app exists.** Publisher exposes a COM automation interface,
so a short PowerShell or VBScript loop over a folder, exporting each file to PDF
(and `.docx` where the layout is simple), will beat any post-hoc conversion on
fidelity — it's the real renderer.

Everything below about Publisher is the fallback for files missed in that window.

Source: [Microsoft Support](https://support.microsoft.com/en-us/publisher/microsoft-publisher-will-no-longer-be-supported-after-october-2026)

---

## Prior art

**No open-source project pre-flights OOXML against Google's importer.** A search
for this turned up only generic repair tools — e.g.
[docx-repair-tool](https://github.com/Kalana-Gayan/docx-repair-tool), which
round-trips through Markdown and would destroy exactly the layout we're trying
to preserve. The text-box→table approach in this repo appears to be novel.

Libraries worth building on:

| Project | Language | Covers | Notes |
|---|---|---|---|
| [docx4j](https://github.com/plutext/docx4j) | Java (Apache 2.0) | docx, pptx, xlsx | One object model for all three. Closest drop-in upgrade from hand-rolled XML manipulation. |
| python-docx / python-pptx / openpyxl | Python | one each | The standard trio. `python-pptx` exposes embedded media cleanly. |
| [libmspub](https://github.com/LibreOffice/libmspub) | C++ | `.pub` | The library behind LibreOffice's Publisher import. The only open-source Publisher reader. |
| [office_oxide](https://github.com/yfedoseev/office_oxide) | Rust + bindings | docx, xlsx, pptx | Claims 8–100× the Python trio's speed. **Benchmarks unverified.** |

---

## Architecture: Apps Script is the wrong host for the next three formats

Apps Script was the right call for Docs — no infrastructure, staff can use it
immediately. It does not extend:

- **No LibreOffice**, so Publisher is impossible there, full stop
- **6-minute execution cap** — a deck with embedded video will exceed it
- **`XmlService` holds the whole DOM in memory** — large pptx/xlsx will fail

The shape that works: a **Cloud Run container** with LibreOffice plus the Python
libraries, triggered by a Drive folder watch or by the existing web app. Keep
the Apps Script front end as the UI — staff already understand it — and have it
hand files to Cloud Run. That single change unblocks Slides, Sheets and
Publisher together.

---

## PowerPoint → Google Slides

**Assessment: most tractable of the three.**

### Embedded media

Slides strips embedded audio and video on import. But the media is recoverable
from the package:

- Files live in `ppt/media/`
- References are in `ppt/slides/_rels/slideN.xml.rels`, with a relationship
  `Type` ending in `/video`

So: extract each video, upload it to a Drive folder, and — better than simply
dumping the files — **insert a text placeholder on the originating slide holding
the Drive link**. That turns a scavenger hunt into a click, because staff know
which video belonged to which slide.

### Animations and transitions

Strip them. They cannot translate to Slides, and removal is trivial:

- `<p:timing>` — animation timeline
- `<p:transition>` — slide transitions

No loss worth mitigating.

---

## Excel → Google Sheets

**Assessment: audit before converting.**

Google Sheets has closed the formula gap — XLOOKUP, LAMBDA and dynamic arrays
are all supported. Ordinary formulas will mostly survive.

What genuinely breaks is structural rather than formula-level:

| Feature | Migration path |
|---|---|
| VBA macros (`.xlsm`) | **None.** Must be rewritten as Apps Script. |
| Power Query / Get & Transform | None. Rebuild as a query or import step. |
| External workbook links | Break. Need re-pointing at Drive equivalents. |
| ActiveX / form controls | Lost. |
| Pivot tables | Partial — some configurations don't survive. |
| Conditional formatting | Mostly survives; edge cases don't. |

**Recommended first build is an analyser, not a converter.** Scan the estate and
report which workbooks contain macros, Power Query, or external links. In a
school trust, expect the large majority to be simple mark sheets that convert
cleanly, and a small tail of business-critical macro workbooks needing a human
decision. That report tells you whether a converter is worth writing at all.

---

## Publisher → ?

**Assessment: worst format, clearest answer.**

Beyond the pre-retirement export window above, LibreOffice headless is the
fallback:

```bash
soffice --headless --convert-to pdf --outdir ./out ./in/*.pub
```

`.pub` is LibreOffice's weakest import filter. Expect some files to fail
outright and others to open with shifted layout and substituted fonts. Treat it
as triage: convert the batch, then sort into "clean" and "needs a human".

### Why Slides is the right target

`.pub` files in schools are overwhelmingly newsletters, flyers and posters.
Slides' free positioning fits that far better than Docs' text flow.

Route: `.pub` → LibreOffice `.odg` (Draw — also a canvas model, so positioning
survives) → `.pptx` → Slides.

Each hop loses a little, so pair the outputs: **PDF for the faithful archive
copy, Slides for the editable copy.** Staff keep something accurate and get
something they can change.

---

## Method note

The Docs converter's design was validated against four real primary-school
worksheets rather than synthetic tests. Structural probes of those files found:

- 12–22 floating objects per document
- 4–10 text boxes per document
- 100% of anchors classifiable as picture, text box or ink — nothing hit the
  unrecognised-content path
- no document contained a genuine backing picture. An earlier count claiming
  otherwise mistook `mc:Fallback` anchors — Word's legacy restatement of the
  same shape — for separate pictures sitting beneath the text box. 6 of 18
  anchors in one document and 4 of 15 in another are such duplicates, and any
  tool reading anchors must discard them or it double-counts every shape Word
  wrote twice
- 1 document contained handwritten ink annotations
- 1 header background image measured 2480×3508 — A4 at exactly 300dpi, matching
  page aspect to 0.0%

Probing a real sample before writing transforms is strongly recommended. Several
passes were re-scoped as a direct result of what the files actually contained.
