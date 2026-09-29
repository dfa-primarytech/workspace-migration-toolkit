# Handoff

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

---

## Previous handoff

- Agent: Codex (XLSX)
- Date: 2026-09-29
- Branch: `codex/xlsx-live-followups`, based on main `77e08cb`; PR #94
- Objective: Finish the XLSX follow-ups left after #72 and verify native Google Sheets import live.
- Files changed: `xlsx.py`, `jobs.py`, `tests/platform/test_xlsx.py`, `tests/platform/test_xlsx_issue51.py`, `docs/xlsx-migration.md`, and coordination files.
- Completed: cell-limit checks use observed cell extent and separately report stale declared extents; sheet indexes are zero-based; the uncalled stale-workspace sweeper and test are removed; a generated five-sheet workbook converted through real Drive and Sheets APIs, with five sheets confirmed by read-back.
- Checks: 440 passed, 13 skipped; Ruff check and format clean; mypy clean for 25 source files; Bandit and secret scan clean. Live report: 5 sheets, 227 populated cells, 47 formulas, 0 formula errors, native spreadsheet created and structurally verified.
- Known failures: none.
- Unresolved: formula results, charts, formatting, validation and protection still need human visual comparison in the imported Google Sheet. One synthetic live import does not establish broad fidelity.
- Decisions: DECISIONS.md, 2026-09-29 (XLSX extent/index/cleanup and live native import).
- Next task: visually compare the generated workbook against its Expected results sheet, then add targeted regression work only for observed fidelity losses.
- Warnings: the downloaded conversion report contains private Drive file and folder IDs and must not be committed. No school document or OAuth token is in this branch.

---

## Previous handoff

- Agent: Codex (XLSX)
- Date: 2026-09-29
- Branch: `rescue/xlsx-sheets-mvp`, merged with main `4c6d655`
- Objective: Fix issue #51: the `.xlsm` crash, chart-sheet rejection and conflicts with main.
- Files changed: XLSX pipeline modules and tests; shared package, pipeline, worker and web format registration; generated XLSX fixtures and documentation; coordination files. Main's Publisher/platform changes were retained by the merge. The pipeline-selection integration assertion in `tests/platform/test_docx.py` was updated only to recognise main's existing Publisher support.
- Completed: `.xlsm` keeps its source extension and MIME through native import; real VBA is reported as unsupported; chart sheets are retained and reported UNSUPPORTED; dialog and macro sheets require manual migration; generated fixtures cover both issue regressions; current main conflicts are resolved.
- Checks: 440 passed, 13 skipped; Ruff check passed; Ruff format checked 47 files; mypy passed 25 source files; Bandit passed; secret scan passed; JavaScript syntax passed.
- Known failures: none.
- Unresolved: live Google Sheets import remains unverified; cell-limit estimation, one-based sheet-index consistency and the unused sweeper remain follow-ups outside issue #51.
- Decisions: DECISIONS.md, 2026-09-28 (Excel source format and non-worksheet sheets).
- Next task: merge PR #72 after GitHub checks pass, then verify a synthetic workbook against a controlled Google Workspace tenant.
- Warnings: no real school files were used or committed. No GCP resources or credentials were created. Do not treat retained CLI manifests as content-free; they can contain sheet and external-workbook names.
