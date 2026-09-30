# Handoff

- Agent: Claude Code (second session, DOCX stream)
- Date: 2026-09-30
- Branch: `fix/docx-placement-sections`, the top of a stack on main `2d80316`: `fix/docx-page-size` (#114) <- `fix/docx-same-page-geometry` (#134) <- this (#112, #115, #116, #117, #118, #135). `fix/docx-textbox-ends-container` (#113) is on main by itself.
- Objective: fix the DOCX issues from the 2026-09-29 audit and Codex review, split with the Publisher session (which took #105-#111 on `fix/publisher-planning-crashes`).
- Files changed: `docx.py` (`twips`, `page_geometry`, `governing_sections`/`section_of`, `body_blocks`, margin strips in `anchor_position`, `on_an_unknown_side`), `docs.py` (`Sections`, per-section `printable_width`/`printable_height`/`_margin`, `_page_relation`, `_row_cells`/`_cell_at`, `_scale_extent`, `_end_with_paragraph`, `_gained_picture`; `transform` takes a fallback section for headers), tests `test_docx_page_size.py`, `test_docx_same_page.py`, `test_docx_textbox_container.py`, `test_docx_placement.py` (all new), `test_docx.py`, `test_docx_validity.py`, DECISIONS.md, this file.
- Completed:
  - #114: decimal and unit page sizes are read; an unreadable one is refused (`invalid_page_size`), never A4.
  - #134: the geometry pass needs a shown common page (DECISIONS.md, 2026-09-30); `picturesGeometryUncertain` now reaches the saved report.
  - #113: a text box's table no longer ends a cell, header, footer or body.
  - #135, #115: each table, row and placement is measured by its own section's current properties.
  - #112: margin strips are restated from the paper's edge; inside/outside keep today's reading and are counted in `positionsPageSideUncertain`.
  - #117: cells are found through the grid (gridBefore, gridSpan); a vMerge continuation is reported, not filled.
  - #116: a text box's own picture no longer releases its blank lines. #118: a group scales as a whole.
- Checks: the full stack, 540 platform tests passed, 14 skipped; Ruff and mypy clean. Every new test file was run against main: 33 of its 37 tests fail there (the other 4 guard behaviour that must not change).
- Known failures: none.
- Unresolved:
  - #113: whether Word rejects the old output is still unestablished; the new LibreOffice case runs only in CI.
  - #134: the three-block rule for documents without `w:lastRenderedPageBreak` is a judgement, not a measurement.
  - A picture inside a text box, floating in it, is still not inlined when the box becomes a cell (the parent map is stale by then); noticed while testing #116, not changed.
  - Headers and footers are measured by the body's last section; which sections use them is not worked out.
- Decisions: DECISIONS.md, 2026-09-30 (a shown common page; margin strips and page-sided frames).
- Next task: #119, and the empty-drawing residue (#20) the #113 tests ran into.
- Warnings: merge the stack in order (#114, #134, then the placement PR); after a squash merge, the next branch needs rebasing onto main. #113 conflicts with nothing in the stack.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-table-fit`, based on main `e356d7d` (#100 merged)
- Objective: keep PUB-002's tables on the page (page 3's ran off it; so did 7, 8 and 9).
- Files changed:
  - `publisher_slides.py` (`_table_layout`, `room_below`, `TableLayout`, `measured_as`; `rough_height` takes spacing and scale);
  - `publisher_fit.py` (`fit_with`, the search `fit` now uses);
  - `font_metrics/calibri.json`, `arial.json` (new, from Carlito and Liberation Sans) and its README;
  - tests: `test_publisher_table_fit.py` (new, 4), `test_publisher_fit.py`;
  - `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - Measured in the Slides editor: Google pads a cell's text 6.2 to 6.5 pt above and below. With that, the row estimates of all eight tables came within 13 pt of Google's drawing.
  - Tables grow into free space (down to what is below, a box they sit in, or 10 pt from the edge), and only past that is their text made closer, then smaller.
  - Verified live: all eight tables stay on their pages (page 9: 721 to 482 pt).
  - The owner chose readable text over Publisher's exact bottom edge.
- Checks: 506 platform tests passed, 12 skipped; Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - Page 18's bullets sit tight against centred text.
  - The on-screen summaries show the reader's internal notes.
  - The owner wants no Check file button in the final version.
- Decisions: DECISIONS.md, 2026-09-29 (keep tables on the page, readable text first).
- Next task: the bullet gap, then hiding internal notes from staff.
- Warnings: CT 203's `/root/wmt-test/live` holds the OAuth client secret, the Picker key and a picture token (expires 20:42 UTC). `wmt-test-live` runs `wmt-test/app:pub17`. Parsed PUB-002 bundles are under `/root/wmt-test/private`; never commit them.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-tables`, based on main `bc0a4be` (#99 merged)
- Objective: PUB-002's tables: grid lines and the book covers missing from their cells.
- Files changed:
  - `publisher_slides.py` (`grid_borders`; `_inline`, `_with_room`, `rough_height`; U+FFFC dropped from text);
  - `publisher_inline.py` (new), `publisher_art.py` (`Prepared.inline`), `publisher.py`;
  - parser: `main.cpp`, `model.h`, `collector.h`, `bundle.cpp` write `drawing-pictures.bin` (EscherDelayStm); `tests/test_bundle.cpp`;
  - tests: `test_publisher_inline.py` (new, 6), `test_publisher_slides.py`;
  - `docs/publisher-parser.md`, `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - Grid: no record in either booklet holds a border (dumped with a debug libmspub build), yet all print a thin black grid (the owner's print previews). Tables get 0.75 pt black on every cell.
  - Covers: all 7 recovered (inline pictures; libmspub drops shapes not on a page) and placed over their cells.
  - Verified live on PUB-002: pages 11, 12 and 14 match the Publisher screenshots.
- Checks: 502 platform tests passed, 12 skipped; Ruff and mypy clean; the app image builds with the parser's C++ tests passing.
- Known failures: none.
- Unresolved:
  - Page 3's table runs off the page: table rows aren't fitted to their text as text boxes are (next task).
  - Page 18's bullets sit tight against centred text.
  - The on-screen summaries show the reader's internal notes.
  - The debug libmspub patch (table dumps) is only in `/root/wmt-test/dbg` on CT 203, never in the repo.
- Decisions: DECISIONS.md, 2026-09-29 (table grids, and pictures set in text).
- Next task: fit table rows to the page (page 3); the bullet gap; hide internal notes from staff.
- Warnings: CT 203's `/root/wmt-test/live` holds the OAuth client secret, the Picker key and a picture token (expires 20:42 UTC). `wmt-test-live` runs `wmt-test/app:pub14`. Parsed PUB-002 bundles are under `/root/wmt-test/private`; never commit them.
