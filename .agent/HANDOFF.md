# Handoff

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

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-text-wrap`, based on main `d44e17c` (#96 merged)
- Objective: keep text clear of pictures it wrapped around in Publisher. Slides has no text wrap (the human chose option 1: paragraph indents).
- Files changed:
  - `publisher_wrap.py` (new);
  - `publisher_slides.py` (`in_front_of`, `text_requests(extra=)`, `_indent`, notes);
  - `tests/platform/test_publisher_wrap.py` (new, 6);
  - `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - Paragraphs level with a picture in front are indented on its side, with an author's own indent kept.
  - The indents and the text fitting are repeated until stable.
  - A picture only counts if text is level with it (fixes a false note on page 4).
  - **Verified live on PUB-001:** pages 2 and 3 have no text under a picture. They drop to 11 pt to fit.
- Checks:
  - Linux (host): platform and parser suites, with the binary and PUB-001, 544 passed.
  - Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - The author's mid-sentence line breaks (page 3) now leave single words on a line more often. Joining those "soft" breaks is a possible follow-up, awaiting the human's call.
  - The whole paragraph moves: the page 2 heading "blending" wraps because it's level with the frog.
- Decisions: DECISIONS.md, 2026-09-29 (wrap with indents).
- Next task: merge on approval.
- Warnings: CT 203's `/root/wmt-test/live` holds the OAuth client secret, the Picker key and a picture token (expires 14:01 UTC). The container `wmt-test-live` runs `wmt-test/app:pub7`. Remove them when live testing ends.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-crops`, based on main `e36ddd6` (#95 merged)
- Objective: stop cropped Publisher pictures being stretched. The crop was in the file; libmspub dropped it.
- Files changed:
  - `native/pub-parser/src/main.cpp`, `model.h`, `collector.h`, `bundle.cpp` (write `drawing.bin`);
  - `tests/test_bundle.cpp` (new test);
  - `app/workspace_toolkit/publisher_crop.py` (new: read records, match, fit check);
  - `publisher_art.py` (`crop_picture`, `prepare(crops=)`);
  - `publisher_slides.py` (uses the cropped picture; "Cropped as in the original");
  - `publisher.py` (reads crops in the worker);
  - `tests/platform/test_publisher_crop.py` (new, 7);
  - `docs/publisher-parser.md`, `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - The parser saves Publisher's drawing records.
  - The app recovers every picture's crop, matches it, checks it fits its frame, and cuts the picture before upload.
  - On PUB-001 all five cropped placements fit exactly, including the banner cropped two different ways on pages 1 and 4.
- Checks:
  - Linux (host): the image builds, with C++ tests 108/108. Platform and parser suites pass: 503, plus the parser's 59 with the binary and PUB-001 supplied.
  - Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - **Not yet seen in Google.** It needs a live run with a fresh picture token.
  - Outward crops (padding) aren't handled; they're left uncropped and reported.
- Decisions: DECISIONS.md, 2026-09-29 (picture crops).
- Next task: a live run to confirm the pictures on pages 1, 2 and 4, then merge.
- Warnings:
  - CT 203's `/root/wmt-test/live` holds the OAuth client secret, and a picture token that expired at 13:23 UTC. The container `wmt-test-live` is still running.
  - The image `wmt-test/app:pub6` has this branch.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-table-borders`, based on main `03d1980` (#93 merged)
- Objective: stop Publisher tables showing Google's default grey grid, which the original didn't have.
- Files changed:
  - `publisher_slides.py` (`hidden_borders`, sent after `createTable`; the checker knows `updateTableBorderProperties`);
  - `test_publisher_slides.py`;
  - `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - Tables are drawn with transparent borders, and the report says why.
  - libmspub 0.1.4's source confirms it passes on no table borders at all.
  - Verified live on PUB-001: page 1's table has no lines, matching LibreOffice's rendering.
- Checks: Publisher tests pass (66) on Windows; the full Linux suite runs before the PR; ruff and mypy clean.
- Known failures: none.
- Unresolved: real table borders and picture crops both need the `.pub` read directly (the next investigation).
- Decisions: DECISIONS.md, 2026-09-29 (tables without borders).
- Next task: merge on approval. Then the crop investigation: where Publisher keeps a picture's crop, and whether libmspub reads it.
- Warnings: CT 203 still has `/root/wmt-test/live` (the OAuth client secret, and a token expiring at 13:23 UTC) and the running `wmt-test-live` container. Remove both when live testing ends.
