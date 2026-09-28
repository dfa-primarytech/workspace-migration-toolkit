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
| Picture | `createImage`, stretched to its frame as Publisher's bitmap fill is | NATIVE |
| Turned picture | Placed by its outline polygon, not its bounding box | NATIVE |
| Rectangle, ellipse | `RECTANGLE` / `ELLIPSE` with fill and outline | NATIVE (SUBSTITUTED if a gradient became one colour) |
| Straight strokes with no filled area (rules, polylines) | One editable line per segment, grouped | SUBSTITUTED (NATIVE for a single line) |
| Filled or curved drawing | A picture of it | FLATTENED |
| Drawing with no stroke and no area | Nothing | IGNORED, reported |
| Table | `createTable`, column widths, minimum row heights, merges, cell text and fill | SUBSTITUTED: borders are Google's default |
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
stretches it to the frame. Four of PUB-001's pictures are stretched a great
deal (one by about 3.5×). LibreOffice, which uses the same reader library,
draws them the same way. Publisher probably cropped them, and libmspub
0.1.4 does not pass crops on. Each is reported (`picture-stretched`).

## Known limits

- **Crops** are not applied (the reader doesn't pass them on).
- **Mirrored pictures** are reported, not flipped (the reader can't tell which way).
- **Gradients** are drawn in a single colour; the reader does not pass their colours.
- **Self-crossing filled shapes** are filled even-odd, so a star's centre is left empty where Publisher fills it.
- **Text insets**: the Slides API has no setting for the space inside a text box, so text may wrap slightly differently.
- **Table borders** are not described by the reader, so Google's default borders are used.
- **Exact line spacing** has no Slides equivalent; percentage spacing is kept.
- **Page size** is requested in `presentations.create`. Whether Google keeps an A5 size must be checked in step 4 (§14), and step 3 will read the size back rather than assume it.

## Evidence

- Offline tests: `tests/platform/test_publisher_slides.py`, 38 tests. Every document in them is built in the test. They check the geometry by applying each transform as Slides does.
- **PUB-001** (4 pages; parsed in the app image on the test host, never committed):
  - 272 requests with no `check()` problems;
  - pictures within 0.0001 pt of their Publisher frames;
  - 13 NATIVE, 7 SUBSTITUTED (Sassoon → Andika, the rules, the table), 2 IGNORED (the wrapper and a path with no area).

  An offline drawing of the plan matched LibreOffice's rendering of the file. The same test runs wherever `PUBLISHER_FIXTURE_PUB001` and the parser are supplied.
