# Publisher → Google Slides renderer

Step 2 of the Publisher work (DECISIONS.md, 2026-09-28). It turns the
parser's IR into Google Slides API requests, **offline**. No request has
been sent to Google yet. Sending them, with the pictures delivered through
signed Cloud Storage links, is step 3, and a live run with PUB-001 is step 4.
**Nothing below about how Google draws a request is verified until then.**

```text
bundle/ (document.json, assets.json, assets/)
   │
   ├─ publisher_art.prepare()    pictures Slides can take, drawn paths, composed borders
   │
   └─ publisher_slides.plan()    presentations.create body
                                 + one blank slide per page
                                 + one list of batchUpdate requests per page
                                 + a report line for every element
```

| Module | Does |
|---|---|
| `units.py` | Length strings to points, and the frame → Slides transform (§19). The only place with unit or placement arithmetic |
| `publisher_art.py` | Files: converts or shrinks assets Slides would refuse, draws paths no Slides shape can express, composes border art |
| `publisher_slides.py` | Pure: the plan, `bind()` to swap picture keys for links, and `check()` for anything Google would refuse |

## What each element becomes

| IR | Slides | Status |
|---|---|---|
| Page | A blank slide, in order; the presentation is created at the first page's size | — |
| Text frame | `TEXT_BOX`, text inserted once, then each run and paragraph styled by UTF-16 range | NATIVE, or SUBSTITUTED if a font was replaced |
| List paragraphs | `createParagraphBullets`, one per run of the same kind of list | NATIVE, or SUBSTITUTED if the numbering or bullet was approximated |
| Picture | `createImage`, stretched to its frame as Publisher's bitmap fill is | NATIVE |
| Turned picture | Placed by its outline polygon, not its bounding box | NATIVE |
| Rectangle, ellipse | `RECTANGLE` / `ELLIPSE` with fill and outline | NATIVE (SUBSTITUTED if a gradient became one colour) |
| Straight strokes with no filled area (rules, polylines) | One editable line per segment, grouped | SUBSTITUTED (NATIVE for a single line) |
| Filled or curved drawing | A picture of it | FLATTENED |
| Drawing with no stroke and no area | Nothing | IGNORED, reported |
| Table | `createTable`, column widths, minimum row heights, merges, cell text and fill; Publisher's default grid (0.75 pt black on every cell) | SUBSTITUTED: the file stores no borders to read |
| Picture set inline in text (U+FFFC) | Recovered from the drawing records (`publisher_inline.py`) and placed over its table cell, centred as its paragraph is, with that line's space above kept free for it | NATIVE, reported: Slides can't hold a picture in a table |
| Border art | Each border's tiles combined into one picture | FLATTENED |
| Authored group | `groupObjects` over what its contents became | NATIVE; reported if it holds a table or fewer than two items |
| Wrapper layer | Nothing of its own; its contents are drawn | IGNORED |
| Hidden element | Nothing | IGNORED |
| Unknown element | Nothing | UNSUPPORTED |
| Picture that could not be read | A dashed red box saying so, where it was | UNSUPPORTED |

Paint order is creation order: each page's elements are made in `zIndex`
order, so the last thing Publisher drew is on top.

Content that appears identically on every page is marked as probably coming
from the master page. It is still drawn on every slide, as readiness §7.5
decided.

## Pictures and their links

A `createImage` carries `wmt-picture:<key>` until `bind()` swaps in a real
link. `Plan.keys_for(page)` lists the keys one page needs, so step 3 can
upload, sign and send a page at a time within the 15-minute link lifetime.
`check(plan, bound=True)` fails on any picture left without a link.

Slides fits a picture inside the size it is given without distorting it.
So each picture is given a size in its own proportions, and the transform
stretches it to the frame.

**Crops are recovered from the file** (`publisher_crop.py`). libmspub reads
each picture's crop and drops it, so a cropped picture used to be stretched
into its frame. LibreOffice still draws it that way. The parser now saves
Publisher's drawing records (`drawing.bin`), and the app reads the four "crop
from" values of every picture shape.

It matches each stored picture to the reader's asset by size, and a picture
used more than once to its placements in whichever order makes every one fit.
A crop is applied only when the cropped picture then has its frame's own
shape, within 3%; otherwise the picture is left as it was and the report says
so. The cropped part is cut out before upload (a photograph stays JPEG) and
reported as "Cropped as in the original".

On PUB-001 all five cropped placements fit exactly. They include the banner,
one picture cropped two ways: a thin strip on page 1, trimmed further on the
right on page 4. A picture that is still out of shape after all this is
reported (`picture-stretched`).

## Known limits

- **Lists** come from the patched libmspub (docs/publisher-parser.md); the stock 0.1.4 never passes them on. Each run of consecutive list paragraphs of one kind becomes one `createParagraphBullets`, sent before the paragraph styles so Publisher's own hanging indents are the ones kept. Numbering maps to the nearest Slides preset (1. and 1), I., A.); anything else is shown as 1, 2, 3 and reported, and so is a bullet other than a dot and a list that started past 1, which Slides can't do. Verified live on PUB-002's 12 bulleted lists.

- **Crops** are applied only when they fit their frame (see above). An outward crop (padding), which Publisher allows, is not handled and leaves the picture uncropped.
- **Mirrored pictures** are reported, not flipped (the reader can't tell which way).
- **Gradients** are drawn in a single colour; the reader does not pass their colours.
- **Self-crossing filled shapes** are filled even-odd, so a star's centre is left empty where Publisher fills it.
- **Text insets**: the Slides API has no setting for the space inside a text box, so text may wrap slightly differently.
- **Table borders** are drawn as Publisher's default grid: a thin (0.75 pt) black line on every cell edge. Neither PUB-001 nor PUB-002 stores a border setting anywhere: the table and cell records in Contents, the table's text records (TCD) and its drawing record were all dumped with a debug build of libmspub. Yet every table in both prints a thin black grid, as the owner's Publisher print previews of PUB-002 pages 3 and 12 show. The width is estimated from those previews. A table whose author changed or removed its lines has not been seen yet; when one is, its records will show where Publisher keeps them. This replaces the invisible borders of #95.
- **Tables are kept on the page.** Slides grows a row to its text and never below its own height, so a table laid out Google's way can run past the page: PUB-002's page 9 table drew 721 pt tall where Publisher's was 319. Each row's height is estimated from its tallest cell (real metrics for Andika, Calibri and Arial; Google's 6.4 pt of padding above and below a cell's text, measured in the editor). The table may grow into free space below it, down to whatever is below, the bottom of a box it sits in, or 10 pt from the page's edge. Only past that is its text set closer, then smaller, the same throughout the table, as for a text box. Readable text was preferred to Publisher's exact bottom edge (the owner's choice). Checked live: the estimates of PUB-002's eight tables came within 13 pt of Google's drawing, and every table then stayed on its page.
- **Fonts Slides doesn't have** (such as Amasis MT Pro) are drawn in Arial, and measured as Arial.
- **Inline pictures** are placed by estimate. Slides has no pictures inside tables, so each goes over its cell, in room its line leaves above itself. Its height comes from the table's own row heights and the text above it, laid out with real metrics where the font has them (Andika) and at half an em a character where it doesn't. A picture is only placed when the drawing records hold exactly as many unplaced picture shapes as the text has U+FFFC marks; they are paired in Contents sequence order (PUB-002: 7 and 7, and each stored size matched its picture's own shape to three decimal places). Otherwise the marks are dropped and the pictures reported missing.
- **Exact line spacing** has no Slides equivalent; percentage spacing is kept.
- **Page size (§14), settled live.** `presentations.create` accepts a `pageSize` and ignores it: A5 came back as 720 × 405 pt. The presentation is therefore made by importing an empty PowerPoint deck of the publication's size (`publisher_deck.py`), which Google keeps. The size is still read back and reported if it differs.
- **Text is fitted to its box** (`publisher_fit.py`). Publisher sized each frame for its original font. Andika, which replaces Sassoon, has wider letters, so the same text wraps onto more lines. On the first live run it ran off pages 2 and 3, and under the frog on page 2.

  Each frame is laid out beforehand with Andika's real advance widths (`font_metrics/andika.json`, extracted by `scripts/font_metrics.py`; no font file ships), in Google's own line geometry. If it would overflow:
  - its line spacing is tightened, to no less than 90%;
  - only then are its sizes reduced, evenly, to no less than 75%.

  Each change is reported, and so is text that still won't fit. A frame in a font without measurements is left alone.

  **Google's geometry, measured on the live slides (2026-09-29):**
  - lines are **1.2 times the font size** apart at 100% spacing, whatever the font; Andika's own metrics say 1.61, and Google ignores them;
  - the text box's inner margin is **7.2 pt at the sides**.

  With those numbers the estimate for PUB-001's page 2 landed within 2 pt of where Google put the last line.

  On PUB-001:
  - pages 2 and 3 keep their 12 pt text, with lines 10% and 5% closer;
  - the web address on page 4 goes to 85% so it stays on one line;
  - everything else fits as it is.

  In Google, page 2's text ends at 554 pt and page 3's at 548 pt, both inside their 591 pt boxes on a 595 pt page.
- **WordArt becomes editable text** (`publisher_wordart.py`). libmspub passes WordArt on as outlines only: a gradient-filled shape with no area, and one stroked baseline per line. PUB-001's title "Early Reading at St.Vincent's" came through as two purple lines. The words, font, size, weight and colours are the WordArt shape's own properties in `drawing.bin` (0xC0, 0xC5, 0xC3, 0xFF, 0x181, 0x1C0).

  Each WordArt is matched to the outline libmspub drew for it: a layer of paths in the WordArt's own line colour, in drawing order. It's drawn there as a centred text box, as large as fits (WordArt stretches to its box; Slides can't), with the outlines left out. Its shaping, gradient and effects such as a reflection aren't recreated, and the report says so. A WordArt that can't be placed is reported with its words, so nothing is lost silently.
- **Text wraps around pictures by indenting** (`publisher_wrap.py`). Slides can't wrap text: it runs straight under a picture. Publisher wraps text around any object in front of its frame, so each paragraph level with such a picture is indented on the picture's side, just far enough to clear it plus 3.6 pt. The text stays one editable box, with ordinary paragraph indents. An author's own indent is kept, and only a shortfall is made up.

  Positions come from the fitting layout. Indenting and fitting are repeated until they settle, so wrapped text still fits (on PUB-001, pages 2 and 3 go to 11 pt). Limits, each reported:
  - a whole paragraph is indented, even if only part of it is level with the picture;
  - text keeps to the wider side of a picture in the middle;
  - a picture across more than 60% of the line can't be kept clear and stays over the text.

  Verified live on PUB-001: the frog, the letter cards and the book pictures on pages 2 and 3 no longer cover any text.
- **Hand-made line breaks.** Where an author pressed Enter mid-sentence to steer text around a picture, the break was placed for the original font. In Andika the last word can land on a line of its own (PUB-001 page 3). These breaks are part of the document, so they're kept.

## Evidence

**Live run, PUB-001, 2026-09-29.** Converted through the app on the test host into a real staff account's Drive:

- 4 A5 portrait slides, in order;
- all 22 items on the right slides, and every text box's text as planned (read back and checked);
- Sassoon shown as Andika;
- the two rules as editable lines;
- the table with its text;
- all 12 pictures, including a scannable QR code;
- the bucket empty afterwards.

It took two fixes to get there, both found only by Google:
- the page size (above);
- Publisher's paragraph marks. The reader leaves a carriage return at the end of each paragraph, and Slides drops it on insert, so every later text range overran and Google refused every page. They are now stripped, the checker refuses them, and the fake Google in the tests drops them as Google does.

Seen on the slides, and reported:
- Google's default table borders (Publisher's table had none);
- four stretched pictures;
- text flowing slightly differently from the original.

- Offline tests: `tests/platform/test_publisher_slides.py`, 38 tests. Every document in them is built in the test. They check the geometry by applying each transform as Slides does.
- **PUB-001** (4 pages; parsed in the app image on the test host, never committed):
  - 272 requests with no `check()` problems;
  - pictures within 0.0001 pt of their Publisher frames;
  - 13 NATIVE, 7 SUBSTITUTED (Sassoon → Andika, the rules, the table), 2 IGNORED (the wrapper and a path with no area).

  An offline drawing of the plan matched LibreOffice's rendering of the file. The same test runs wherever `PUBLISHER_FIXTURE_PUB001` and the parser are supplied.
