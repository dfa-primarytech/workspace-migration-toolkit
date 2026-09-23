# Publisher renderer readiness

The review package that `PROJECT.md` §38 requires before any Google Slides
rendering begins. **No renderer code exists, and none should be written until
this has been reviewed and approved.**

- Date: 2026-09-23
- Basis: `main` at `46a7648`, libmspub 0.1.4 and librevenge 0.0.5
- Evidence: one real document (PUB-001), the libmspub-0.1.4 source, and the
  parser's test suites. Nothing here has been rendered into Google Slides.
  **Every statement about Google behaviour below is marked unverified**,
  because none has been checked.

## Verdict

**The parser boundary is ready. The renderer is not ready to start**, because
two blocking questions remain open, both of them about Google rather than about
Publisher:

1. **Page size (§14).** PUB-001 is A5 portrait, 420.94 × 595.28 pt. Whether a
   presentation of that size can be created reliably is unverified, and every
   school document depends on it.
2. **Which renderer route.** Build slides through the Slides API, or write a
   `.pptx` from the IR and reuse the existing native-import path. The two
   routes have different answers to the page-size, image-delivery and
   editability questions (see *Recommended changes*, item 1).

A one-to-two-day spike answering both, recorded in `DECISIONS.md`, should come
before renderer code. Everything else below is known well enough to plan
against.

## 1. The resulting document model

Three JSON files and an asset directory, schema `1.0.0`, validated by
`packages/document-model/validation.py`. Full design is in
`docs/publisher-parser.md`.

| File | Holds |
|---|---|
| `document.json` | Pages (with physical size in points and paint order), a flat element list, fonts, counts |
| `assets.json` | Every extracted asset: SHA-256, MIME (declared vs sniffed), pixel size where readable, every placement |
| `report.json` | Diagnostics with page and event index, limitations, callback counts, truncation state |
| `assets/<sha256>.<ext>` | The payloads, deduplicated by content |

Per element: `type` (text, image, table, shape, line, path, group, wrapper,
unknown), bounds in points, `rotationDegrees` (counter-clockwise), z-order,
`parentId`, a compatibility **candidate** with its evidence, warnings, and the
raw librevenge properties (`source.properties` and `source.styleProperties`). The raw
properties let a renderer revisit a parser decision without re-reading the
`.pub`.

Text is paragraphs → runs → items. Spaces, tabs and line breaks are kept as
their own items. Runs carry font family, size, bold, italic, underline, colour
and language. Everything else libmspub sends (indents, margins, padding,
vertical alignment, text columns, drop caps, text shadow, outline, relief,
letter scaling) is **kept verbatim in the style properties but not
interpreted**. A renderer that wants it must read it from there.

## 2. Extracted asset inventory (PUB-001)

Measured on the real document, counts only:

| | |
|---|---|
| Image placements | 12, all through the bitmap-fill route, all axis-aligned rectangles |
| Distinct assets | 11 (8 PNG, 3 JPEG); one reused across two pages |
| `drawGraphicObject` calls | 0 |
| Pages | 4, A5 portrait (148.5 × 210 mm: A4 halved exactly) |
| Elements | 22: 6 text frames (4 with content), 12 images, 1 table (1×3), 2 paths, 1 layer |
| Text | 82 paragraphs, 147 runs, 204 insertions, 143 explicit spaces, 1 line break |
| Fonts | SassoonPrimaryInfant (138 runs), SassoonPrimaryType (8), Calibri (1) |
| Candidates | 19 NATIVE, 2 FLATTENED (the paths), 1 IGNORED (the layer) |
| Diagnostics | 0 |

## 3. Parser test results

| Suite | Result |
|---|---|
| C++ unit tests (`pubir-tests`) | **105/105** in CI, in both the native job and the container build |
| Python schema, validator and CLI tests | 55 run. 33 pass and 22 skip in CI, where the private fixture is absent |
| PUB-001 acceptance | Passed locally on 2026-09-22 with zero diagnostics. **Must be re-run** after #37 changed how layers are classified. Not runnable on CI by design |
| Python lint | Green (#28) |

The C++ suite now includes tests shaped on the callback sequences libmspub
0.1.4 actually emits (`tests/test_libmspub_shapes.cpp`). Tests for callbacks
it never emits are kept, since the model is source-independent, and labelled.

## 4. Unsupported and partly supported Publisher constructs

What reaches the IR, and what a renderer would inherit:

| Construct | In the IR | Renderer implication |
|---|---|---|
| Text frames, runs, basic styling | Full | Map to text boxes (the PUB-001 majority) |
| Tables | Column widths, cells, spans, paragraphs. **No row heights** (`table-row-heights-unknown`) | Row heights must come from content |
| Raster pictures | Asset plus placement, rotation recovered from outline | Map to images |
| Flipped pictures | `outline-mirrored` warning; **the bitmap is not mirrored** | Mirror the asset before upload, or report |
| Cropped pictures | Clip path kept on a wrapper layer (`layer-clip-path`), **not applied** | Apply the crop to the asset, or report |
| Picture recolour and brightness | Kept in style properties, not applied | Apply before upload, or report |
| Groups | Probable groups inferred from layers (`probable-authored-group`), conservatively | Group them, or flatten the hierarchy. Either way nothing is lost |
| BorderArt | One image per tile (`probable-border-art`). A single border can be dozens | Render the tiles, compose them into one image, or report. **Decision needed** |
| Master pages | **Indistinguishable.** Master content is painted into every page | Repeated on each slide. Detectable only heuristically |
| Arbitrary paths and polygons | Kept verbatim; FLATTENED or SUBSTITUTED candidates | Rasterise, or approximate with the nearest shape |
| Metafiles (WMF/EMF) | Extracted; FLATTENED candidate | Rasterise before upload |
| Text in columns, vertical alignment, drop caps | Kept verbatim, not interpreted | Interpret per property, or report |
| Shadows | Simple shadows as style properties | Apply or report. See *libmspub limitations* for the rest |
| Lists, hyperlinks, fields | **Never emitted by libmspub 0.1.4** | Not recoverable through this library |
| Embedded fonts | Recorded (name, MIME, size), **not extracted** by policy | Licensing decision, not a parser one |

## 5. libmspub limitations

These happen *upstream* of the parser. We can't see them in the callback
stream, so the conversion report must state them as known limits rather than
as findings about a particular file.

1. **Non-conforming shadows are dropped silently.** Shadows outside
   LibreOffice's model are skipped (a `TODO` in `MSPUBCollector.cpp`).
2. **Malformed table cells are skipped** with a debug message only: cells
   that overflow the table, or have zero or negative spans.
3. **Text-encoding guesswork.** When the character set can't be detected,
   libmspub falls back to Windows-1252. Its own comment describes that as
   "pretty likely to give garbage text". Older or non-English files are most
   at risk. **Recommended:** add a parser diagnostic for text with implausible
   character distributions or replacement characters.
4. **Rotation and flips are not reported** for anything but text. The parser
   recovers rotation from rectangular outlines. It can't recover it from
   non-rectangular shapes, where only the rotated points survive.
5. **Groups, master pages, lists, links and fields are not emitted** as such
   (see section 4).
6. **No crop, recolour or mirror is applied to image payloads.** They are
   described in properties and left for the consumer.
7. **Format versions.** libmspub has separate parsers for Publisher 97 and
   2000 files and one for later versions. Which versions the schools' files
   use is unknown. PUB-001 is a modern file.

## 6. Proposed renderer mapping

Design intent only. **Every Google-side behaviour here is unverified** and is
exactly what the spike must establish.

| IR | Slides-API route | IR → `.pptx` route |
|---|---|---|
| Page size | `presentations.create` with a page size, or a sized template copied (§14) | `p:sldSz` in the package, then native import |
| Page order | One slide per page, in order; `kind: "master"` pages never rendered separately | One slide per page |
| Text element | Text box shape, `insertText`, `updateTextStyle` and `updateParagraphStyle` per run and paragraph | `p:sp` text body with runs |
| Image | `createImage` from a URL Google can fetch, which needs an upload route consistent with `drive.file` | Picture part embedded in the package |
| Rotation | Page-element transform, computed centrally (§19) from `rotationDegrees` and bounds | `a:xfrm rot` |
| Shape (rectangle, ellipse) | `createShape` of the matching type | `a:prstGeom` |
| Line | `createLine` | Connector or line shape |
| Table | `createTable` then per-cell text | `a:tbl` |
| Group | `groupObjects` over the children | `p:grpSp` |
| Z-order | Creation order follows `zIndex`, or explicit reordering | Order in the shape tree |
| Fonts | `workspace_toolkit.fonts` decides, the renderer applies. No Publisher-only table | Same |
| Unsupported | Reported, never skipped (§16) | Same |

Units must go through one conversion module (§19). The IR is already in
points throughout.

## 7. Recommended architectural changes

1. **Decide the renderer route in the spike, with evidence.** The existing
   PPTX and DOCX pipelines don't build documents through Google's APIs: they
   upload a package and let native import convert it (`pipelines.py`,
   `google.convert`). An **IR → `.pptx` renderer** would reuse that path, the
   preflight and the reporting, embed images without an image-URL route, and
   state page size in the package. What it would give up is control: native
   import makes its own decisions, which are then read back and reported
   rather than dictated. A **Slides-API renderer** gives precise control, but
   needs the page-size mechanism (§14) and a way to get images to
   `createImage` under `drive.file`. Both satisfy §4, since either consumes
   only the IR. The spike should convert PUB-001's IR both ways and compare
   the results.
2. **A Publisher pipeline entry.** `.pub` isn't a zip package, so it needs its
   own `Format` and preflight in the platform's registry. The preflight would
   run `publisher-parser` as a subprocess **with a hard timeout**; the parser's
   `--max-seconds` can't catch a hang inside libmspub. This touches
   platform-owned files, so it's a joint change with the platform stream.
3. **Fonts: resolve the Sassoon case before rendering.** 146 of PUB-001's 147
   runs use Sassoon Primary, a handwriting family used for early reading.
   The shared service correctly leaves it UNKNOWN or for manual review rather
   than guessing, so a converted booklet would show whatever fallback the
   viewer has. That needs a product decision, such as a school-supplied alias
   or an explicit report line, not a renderer workaround.
4. **Border art: decide the default.** Options: render every tile (faithful,
   many objects, hard to edit), compose each border into one image
   (FLATTENED, reported), or omit it and report (IGNORED). Recommendation:
   compose and report, because editability of the content inside matters more
   than the frame (§33).
5. **Master content: report, don't strip.** Master content arrives on every
   page with no marker. A renderer could detect elements repeated identically
   across pages and report them as probable master content. It shouldn't
   remove or merge them automatically.
6. **Asset pre-processing stage.** Crop, mirror, recolour, brightness and
   metafile rasterising all belong in one step between the IR and the renderer.
   It works on copies of the extracted assets and reports every change as
   FLATTENED or SUBSTITUTED. Parser output stays the unmodified source.
7. **Text-encoding diagnostic in the parser** (section 5, item 3), before any
   older or non-English files are converted.

## 8. What approval is being asked for

1. The **spike** in section 7, item 1, including the page-size question from §14.
2. The **defaults** for border art (7.4) and master content (7.5).
3. A **decision on handwriting fonts** (7.3), owned by the shared font service.

Renderer implementation should start only after those three, per §38. The
breadth gap stays open as well: grouped, rotated, flipped, cropped,
border-art and older-format `.pub` files (PUB-002 onwards) are the evidence
that would turn the source-derived findings above into measured ones.
