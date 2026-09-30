# Handoff

- Agent: Claude Code / QuietHeron (platform UI)
- Date: 2026-09-29
- Branch: `feat/one-step-convert`, based on main `2d80316` (#103 merged)
- Objective: the owner's direction (DECISIONS.md, 2026-09-29): a teacher picks files, presses Convert, gets Google files; no notes on screen; bulk conversion.
- Files changed: `static/app.js` (rewritten), `static/index.html`, `static/style.css`, `web.py` (the source fingerprint is optional), `tests/platform/test_web.py`, this file.
- Completed:
  - One screen for every format: choose files (several at once, or from Drive with multi-select, folders browsable), then one Convert button.
  - Files convert one after another, each row showing "Converting…", then "Open in Google Slides/Docs/Sheets · Folder", or "Couldn't convert: <reason>".
  - No Check file button, no summary, no notes list, no report download on screen: the report is in each conversion's folder.
  - `/api/convert` no longer needs a prior check. A client that sends `X-Source-Sha256` is still held to it (409 `source_changed`).
  - `/api/analyse` and the CLI are unchanged.
- Checks: 510 platform tests passed, 12 skipped; Ruff and mypy clean. The page was previewed in the browser pane with sample files, at desktop and phone width, with no console errors. No real conversion was run through the new page: the picture token had expired and the pane was signed out.
- Known failures: none.
- Unresolved:
  - A live run of several files, one from Drive, through the new page.
  - Google's sign-in lasts an hour: a long batch may need the teacher to sign in again part-way. Each file checks this before it starts.
  - "A whole folder" means selecting every file in the picker (drive.file scope), not pointing at a folder.
- Decisions: DECISIONS.md, 2026-09-29 (built for a frustrated educator).
- Next task: a live run; then decide whether `/api/analyse` stays at all.
- Warnings: this changes the screen every format shares. DOCX, PPTX and XLSX conversion code is untouched. CT 203's `wmt-test-live` runs `wmt-test/app:pub19`; its picture token has expired.
---

## Previous handoff

- Agent: Claude Code (Claude 2, DOCX/platform/parser)
- Date: 2026-09-30
- Branch: `docs/handoff-readback`, based on main `82213d0`. All my PRs are merged: #167 (#55), #169 (#168), #171 (#53), #172 (#54).
- Objective: the last audit and backlog issues in my split with Claude 1: #55, #168, #53, #54.
- Files changed (across those PRs): `docs.py` (`_place_above` containment and `_table_start`; `saved_page_count`, `topLevelTables`/`sourcePages` in `render`; `convert` calls the read-back and, when the setting is on, the repair); `readback.py` (new: `document_facts`, `findings`, `read_back`, `separators`, `repair_requests`, `repair_blank_pages`); `pdf_pages.py` (new: a bounded page-count and blank-page reader); `google.py` (new methods only: `document`, `export_pdf`, `batch_update`, and `PDF_EXPORT_LIMIT`); `config.py` (`docx_repair_blank_pages`, env `WMT_DOCX_REPAIR_BLANK_PAGES`); `pipelines.py` (Word `needs_settings`); `docs/platform.md`; DECISIONS (#53, #54); tests `test_docx_straddling.py`, `test_docx_table_position.py`, `test_docx_readback.py`, `test_docx_blank_page_repair.py`.
- Completed:
  - #55: a picture above a table moves only if it fits wholly in one column; straddlers leave their stack and are counted as uncertain once across both passes.
  - #168: those columns are placed where the table says (`tblInd`, `jc`, `tblpPr`); an inexact position leaves and reports the pictures.
  - #53: after a Word import, `documents.get` and a PDF export give `readBack` in the saved report only: floating pictures, lost tables, page-break-only paragraphs, a changed page count, probably-blank pages. Counts and page numbers, never text; a failed read is recorded, never a failed conversion.
  - #54: optional repair, off by default. When on and blank pages were found, one `batchUpdate` guarded by `requiredRevisionId` sets empty separator paragraphs to 1 pt with no keep-together or spacing, then recounts pages. Reported under `readBack.repair`.
  - Every new test failed on the code below it in CI first; each PR names its red run.
- Checks: 658 platform tests pass on main (Claude 1's count after #172); Ruff, mypy and the secret scan clean.
- Known failures: none.
- Unresolved, all for the live test on the test host:
  - #53 has only met a fake Google. Check that a real conversion's `readBack.checked` includes `pdf` with a page count. If it says `"unavailable": {"pdf": "unreadable"}`, the small reader can't open Google's PDFs; `pypdf` is the fallback.
  - Whether "probably blank" is useful or noisy on real worksheets.
  - #54 stays off until `documents.batchUpdate` under `drive.file` is shown to work; then try it on a worksheet with blank pages and compare `pagesBefore`/`pagesAfter`.
  - `tblInd` is read to the table's leading edge (ECMA-376); Word's pre-2013 layouts differ by a cell margin, not modelled.
- Decisions: DECISIONS 2026-09-30 for #53 (report only; own PDF reader; not verified live) and #54 (optional, off by default).
- Next task: none claimed. The only open issue is #5 (a standing request for real files).
- Warnings: the scratchpad venv's `.pth` points at `wmt-docx-fixes/app`, and the worker subprocess gets a fixed environment without `PYTHONPATH`, so tests run from another checkout convert with this checkout's code. Run `scripts/check_secrets.py` before pushing: `detect-secrets` flags a variable named `SECRET` even in a test.
---

## Previous handoff

- Agent: Claude Code (Publisher session, on Platform/PPTX files by the owner's request)
- Date: 2026-09-30
- Branch: `fix/pptx-package-edits`, stacked on `fix/publisher-mask-budget` (PR #140): merge #138, #139, #140, then this
- Objective: #124, #136, #137: package parts edited by regex left packages that no longer held together.
- Files changed:
  - `package.py` (new: `tags`, `attribute`, `RELATIONSHIPS`, `OVERRIDES`, `without_relationships`, `without_overrides`, `with_default`, each confirmed by re-parsing);
  - `pptx.py` (`EMPTIED` only takes an extension with a `uri`; `_strip_part` checks every `a:ext` survives; `strip_videos` uses the helpers and refuses a video whose rels or content types can't be confirmed);
  - `pictures.py` (paired Relationship tags retargeted; overrides and the JPEG Default via the helpers; unconfirmed content types leave the file unchanged);
  - `tests/platform/test_package_edits.py` (new, 8); `docs/platform.md`; this file.
- Completed:
  - #124: a shape size written `<a:ext ...></a:ext>` no longer goes when a video is removed.
  - #136: paired `<Relationship>`/`<Override>` tags for a removed video are removed; a rels part still naming the video after editing refuses the removal.
  - #137: a prefixed `[Content_Types].xml` gets its JPEG Default in its own prefix; the old PNG override goes, paired or not.
  - The 4 end-to-end tests fail on main and pass here; the 4 helper tests can't load on main.
- Checks: 540 platform tests passed, 14 skipped; Ruff clean; mypy only reports `hypercorn` missing locally.
- Known failures: none.
- Unresolved: parts are still edited as bytes (to keep the rest of each part exactly as written), but every edit is now re-parsed and checked. Not tried against a real deck from another tool.
- Decisions: none new.
- Also opened, each on `main` and independent (no `.agent/` changes, so recorded here):
  - #151 (#132): a failed Picker load is forgotten and retried; `tests/platform/test_picker_load.py` runs `app.js`'s own `loadPicker` under Node.
  - #152 (#131): `WMT_REQUIRE_READERS=1` in both validity workflows makes a missing LibreOffice fail its tests; the DOCX job also fails on any skip.
  - #154 (#130): the worker leads its own process group and a stopped job kills the whole group, parser included. Linux-only tests; draft PR #155 runs them on main's code to show they fail there (close it after).
  - Filed #150 (an expired sign-in fails every remaining Publisher page), from Claude 2's review of #139.
  - #150, stacked on #145 (`fix/publisher-expired-sign-in`): Slides answering a page with 401 or 403 stops the conversion (`session_expired` / `google_forbidden`, detail `stopped_at_page_N`) instead of failing every later page; the partial report and links are kept.
- Next task: none claimed. Claude 2 is taking the native parser issues (#126-#129) through Linux CI. `pptx.py`/`pictures.py`/`package.py` are Platform-owned: say so if the Platform stream is active.
- Warnings: in this environment, a heredoc passed through Python can lose a backslash level: after writing a regex that way, search the file for control characters (bytes 1 to 8), or write the edit with the Edit tool instead.
