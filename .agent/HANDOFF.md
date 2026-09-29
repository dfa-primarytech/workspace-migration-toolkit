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

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-text-fit`, based on main `43155f3` (#92 merged), PR #93
- Objective: fit substituted text inside its frame. PUB-001's live run showed Andika text running off pages 2 and 3, and under the frog on page 2.
- Files changed:
  - `publisher_fit.py` (new: layout with Andika's real widths in Google's measured line geometry; spacing, then size);
  - `publisher_slides.py` (`measured`, `text_requests(fitted=)`, sizes scaled to half points);
  - `publisher_convert.py` (the summary groups notes by wording, so different percentages aren't merged);
  - `font_metrics/andika.json` and its README (new: numbers only, no font file);
  - `scripts/font_metrics.py` (new: the extractor, run by hand with fontTools);
  - `pyproject.toml` (package data);
  - tests `test_publisher_fit.py` (new, 10) and `test_publisher_convert.py`;
  - `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - **Verified live with PUB-001, three runs on 2026-09-29.** The first fitting used Andika's own line height (1.61 em) and overcorrected.
  - Measuring the rendered slide in the Slides editor showed Google uses 1.2 em and a 7.2 pt side inset. With those, page 2's last line landed within 2 pt of the estimate.
  - Final result: pages 2 and 3 keep 12 pt with lines 10% and 5% closer; their text ends at 554 and 548 pt, inside 591 pt boxes. Page 4's web address goes to 85%.
- Checks:
  - Windows: the Publisher tests pass (66). Linux (host): the full suite passed before calibration (469). The calibrated build ran live.
  - Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - Default table borders (the original had none).
  - Stretched pictures (the crop investigation).
  - Hand-made line breaks can leave one word on a line in the new font. This is kept deliberately.
- Decisions: DECISIONS.md, 2026-09-29 (fit substituted text).
- Next task: merge #93 on approval; then the table borders, and the crop investigation.
- Warnings:
  - CT 203: `/root/wmt-test/live` holds the OAuth client secret and a picture token that expires at 13:23 UTC, root-only. The container `wmt-test-live` is running. Remove both when live testing ends.
  - `wmt-test/app:pub3` and `:pub4` hold this branch's build.
