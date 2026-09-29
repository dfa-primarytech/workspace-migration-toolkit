# Handoff

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

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-lists`, based on main `077c206` (#98 merged)
- Objective: Publisher lists (route A: a patched libmspub), and PUB-002's "took too long to analyse".
- Files changed:
  - `native/pub-parser/libmspub/` (new: `build.sh`, patches 0000 and 0001), `CMakeLists.txt`, `src/main.cpp` (`--version` names the patches), `.gitattributes`;
  - `Dockerfile`, `docker/publisher.Dockerfile`, `.github/workflows/publisher.yml` (all build the patched libmspub);
  - `publisher_slides.py` (`list_requests`), `publisher_art.py` (faster shape drawing);
  - `worker.py`, `jobs.py`, `web.py` (`check_only`: Check file no longer plans a Publisher file's slides);
  - tests: `test_publisher_lists.py` (new, 6), `test_publisher_app.py` (+2);
  - `docs/publisher-parser.md`, `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - Lists: PUB-002's 12 bulleted lists are real Slides lists (verified live).
  - PUB-002 check 0.6 s (it timed out); its slides plan in 5 s instead of 34. The shapes are drawn as coverage masks averaged down, and the colour is laid on at full size; the result was compared on white against the old drawing (max difference 26/255 on 0.002% of edge pixels).
  - The human compared all 19 pages with Publisher: most match.
- Checks: 497 platform tests passed, 12 skipped; Ruff and mypy clean. The Ubuntu parser image builds with the patched library.
- Known failures: none.
- Unresolved (all seen on PUB-002 against the human's Publisher screenshots):
  - Book covers inside table cells (pages 11-14) never reach the IR: the reader drops them, probably as pictures inline in the cells' text.
  - Table grid lines (pages 3, 7-9, 11-14; PUB-001 too): libmspub never parses borders.
  - Page 3's table text overflows the page: table rows aren't fitted the way text boxes are.
  - Page 18's bullets sit tight against centred text; Publisher leaves a gap.
  - The on-screen summaries show the reader's internal notes ("startLayer/startEmbeddedGraphics is a rendering construct..."): they should stay in the technical report only.
  - The owner wants no Check file button in the final version (DECISIONS.md).
- Decisions: DECISIONS.md, 2026-09-29 (Check file button; route A).
- Next task: tables: borders and in-cell pictures from the Contents stream, as further libmspub patches; then row fitting and the bullet gap.
- Warnings: CT 203's `/root/wmt-test/live` holds the OAuth client secret, the Picker key and a picture token (expires 19:36 UTC). The container `wmt-test-live` runs `wmt-test/app:pub12` (tagged `pub3`). PUB-002 is at `/root/wmt-test/private/pub-002.pub`; never commit it.

---

## Previous handoff

- Agent: Codex (XLSX)
- Date: 2026-09-29
- Branch: `codex/xlsx-live-followups`, based on main `77e08cb`; PR #94
- Objective: Finish the XLSX follow-ups left after #72 and verify native Google Sheets import live.
- Files changed: `xlsx.py`, `jobs.py`, `tests/platform/test_xlsx.py`, `tests/platform/test_xlsx_issue51.py`, `docs/xlsx-migration.md`, and coordination files.
- Completed: cell-limit checks use observed cell extent and separately report stale declared extents; sheet indexes are zero-based; the uncalled stale-workspace sweeper and test are removed; a generated five-sheet workbook converted through real Drive and Sheets APIs, with five sheets confirmed by read-back.
- Checks: 469 passed, 14 skipped before the final main reconciliation; Ruff check and format clean; mypy clean for 29 source files; Bandit and secret scan clean. Live report: 5 sheets, 227 populated cells, 47 formulas, 0 formula errors, native spreadsheet created and structurally verified.
- Known failures: none.
- Unresolved: formula results, charts, formatting, validation and protection still need human visual comparison in the imported Google Sheet. One synthetic live import does not establish broad fidelity.
- Decisions: DECISIONS.md, 2026-09-29 (XLSX extent/index/cleanup and live native import).
- Next task: visually compare the generated workbook against its Expected results sheet, then add targeted regression work only for observed fidelity losses.
- Warnings: the downloaded conversion report contains private Drive file and folder IDs and must not be committed. No school document or OAuth token is in this branch.

