# Handoff

- Agent: Codex
- Date: 2026-09-28
- Branch: `rescue/xlsx-sheets-mvp`, main `9f58568` incorporated by merge `92b9d43`.
- Objective: fix issue #51's .xlsm crash, chart-sheet rejection and main conflicts, with generated fixtures and a draft PR.
- Files changed: `app/workspace_toolkit/sheets.py`, `xlsx.py`, `package.py`; `tests/platform/test_xlsx.py`, `test_xlsx_issue51.py` (new); `docs/xlsx-migration.md`; coordination files. CLI conflict resolved to main verbatim. Existing XLSX registration and DOCX test updates were inherited, not newly edited.
- Completed: reproduced FileNotFoundError after archiving a generated .xlsm and invalid_workbook for a generated worksheet/chart-sheet workbook. Uploads now select the correct package and MIME, and check capability for that MIME. Chart sheets are inventoried, preserved and reported; dialog and macro sheets require manual migration. Added 13 regression cases, including the current web call, unsupported MIME recovery and invalid references. Fixed original_name integration, named folders and case-insensitive XLSM MIME validation. Documented manifest retention accurately.
- Checks: `pytest tests/platform tests/publisher -q -rs`: 334 passed, 42 skipped (8 LibreOffice/Poppler, 34 Publisher parser/fixture). Ruff check and format --check over app, platform tests, Publisher Python tests and document-model passed; mypy app passed (20 files); Bandit passed; secret scan and JavaScript syntax passed; 19 Node regressions passed. openpyxl opened both generated chart-workbook formats; CLI preserved their packages and reported converted paths. Windows/Python 3.14, locked development dependencies. No live Google test.
- Known failures: none in executed checks. Two dependency deprecation warnings and an existing unused Bandit suppression warning remain. Native C++ and unavailable rendering/private-fixture checks were not run.
- Unresolved: #51's dimension-based grid estimate, one-based sheet indexes and unused sweeper remain. Live Sheets compatibility remains unverified; the draft includes the inherited XLSX MVP, not only this turn's fixes.
- Decisions: source format retained end to end; chart sheets reported UNSUPPORTED for review, dialog/macro sheets UNSUPPORTED for manual migration; manifest privacy wording corrected. See DECISIONS.md.
- Next task: review the draft and remaining #51 audit items; obtain human approval before any merge.
- Warnings: no GCP resources, credentials or real school documents used or committed. DOCX production and native/ match main; pipelines.py matches the rescued branch. Earlier uncommitted review notes remain untouched in the original checkout.

---

## Previous handoff

- Agent: Claude Code, working the DOCX issue queue at the human's request
- Date: 2026-09-28 (later same day)
- Branch: `fix/docx-header-footer-manifest`, PR #76, split out of #52 (BACKLOG item 12). Based on main after #71/#74/#73 merged.
- Objective: the DOCX finding Claude 2 flagged back on #52 -- `docx.parse` counts anchors in `document.xml` only, while `render` also transforms headers and footers, so the preflight report can under-count.
- Completed: `parse()` now scans every header/footer part too, via a shared `_element_pairs` helper factored out of the body loop so both paths build identical element shapes. They can't be attributed to a numbered page (a header/footer's page range isn't computed by this model), so they land in a new `headerFooterElements` list naming their source part. `analysis_report()` -- the actual reviewer-facing summary -- now folds those into its element counts and warnings too, tagged with the part instead of a page index.
- Checks: 290 passed locally, 8 skipped, 13 pre-existing failures (confirmed present on unmodified main -- a subprocess-parser environment issue in this checkout, not this change). Ruff, format, mypy and Bandit clean.
- Known failures: none caused by this work.
- Unresolved: #53 and #54 are both explicitly design-only and blocked on the live OAuth scope spike in #53 (no GCP access in this environment, so neither can responsibly be built yet). #55's second half (geometry-based orphan-picture placement) is still open, left as a larger follow-up per the previous handoff entry.
- Decisions: none new.
- Next task: #53/#54 need someone with a live Google test tenant to unblock the scope spike first. Until then, #55's second half or #36 (25MB upload limit) are the remaining unblocked DOCX/platform work.
- Warnings: same as before -- don't assume a `test_docx.py`/`test_preflight.py`/`test_web.py` failure here is real without checking it also fails on unmodified `main` first.

---

- Agent: Claude Code / QuietHeron, standing in on DOCX at the human's request
- Date: 2026-09-28
- Branch: `fix/docx-blank-lines-follow-up`, based on main `e81d77e`
- Objective: SilverDog's non-blocking review notes on #56.
- Files changed: `app/workspace_toolkit/docs.py` (comments and constant placement only; no behaviour change), `tests/platform/test_docx_blank_lines.py` (one new test), this file.
- Completed:
  - `empty_paragraphs` now says the set is keyed on element identity, so it holds only while passes move paragraphs rather than copy them.
  - A new test pins that an author's blank line inside a converted text box survives the move into its cell.
  - `FALLBACK` and `WORD_BREAKS` now sit above `source_text`.
  - The explicit-stack walk and its `None` end-of-paragraph marker are explained.
- Checks: platform 296 passed, 8 skipped (main: 295 and 8). Ruff check and format clean; mypy reports no issues in 17 files; Bandit reports no issues. The new test was confirmed to fail when `transform` records *copies* of the empty paragraphs instead of the elements themselves (1 failed), then passes on the real code.
- Known failures: none.
- Unresolved: none from the review. The cell-seam double height SilverDog found is theirs and was addressed in #60.
- Decisions: none.
- Next task: #70 (library folder race) if the platform owner agrees to option 1; otherwise the queue in BACKLOG.md.
- Warnings: `docs.py` is the DOCX stream's. This is a comment-and-test change made at the human's request.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher and platform)
- Date: 2026-09-28
- Branch: `fix/low-severity-audit-52`, based on main `9f58568`
- Objective: triage issue #52's ten low-severity findings against today's main, fix the trivial ones, and hand off the rest.
- Files changed: `app/workspace_toolkit/jobs.py`, `web.py`, `pptx.py`, `static/app.js`; `native/pub-parser/src/main.cpp`, `src/collector.cpp`; `packages/document-model/validation.py`; `tests/platform/test_preflight.py`, `test_web.py`; `tests/publisher/test_cli.py`, `test_schema.py`; coordination files.
- Completed. Seven were fixed:
  - Preflight lets `CancelledError` through after killing the worker, so a job timeout reports as `job_timeout`, not "took too long to analyse".
  - `/api/convert` refuses a Google sign-in with less than `job_timeout` left (`session_expiring`, 401). `/api/analyse` is unaffected.
  - PPTX group children get slide-space bounds through each group's `chOff`/`chExt`, composed through nested groups.
  - `app.js` shows its own message when a reply isn't JSON.
  - `basename()` splits on `\` as well as `/`.
  - `classifyLayer` scans from the layer's own index, so each close costs its own contents, not the document.
  - `validate_bundle` checks each payload's SHA-256.

  Three were not fixed:
  - The library-folder race is filed as #70: no one-line fix works across instances, and cleanup would mean writing to Drive.
  - DOCX analysis ignoring headers and footers is still current in `docx.parse`. It was flagged to SilverDog on #52 and not touched.
  - The PR #39 `mimetypes` item is not applicable: #39 merged with an explicit `EXTENSIONS` table.
- Checks: platform 295 passed, 8 skipped (main: 291 and 8). Publisher unittest: 59 run, 35 skipped (main: 56 run, 34 skipped). The new CLI test needs the native binary, so it skips here. Every new Python test was run against the unfixed code and fails there (7 of 7 platform and validator tests; the CLI test can't run locally). Ruff check and format are clean over `app`, `tests/platform`, `tests/publisher` and `packages/document-model`. mypy reports no issues in 17 files. Bandit is clean. `node --check` on app.js passes, and `request()` was exercised against 413/400 plain-text, 422 JSON, and 200 JSON and non-JSON replies.
- Known failures: none locally. **The C++ changes were not compiled here** (no toolchain on this machine). CI's native job and container build are the evidence.
- Unresolved:
  - The `classifyLayer` change has no timing test. Its correctness rests on the existing classification tests, and its speed on the reasoning in the comment.
  - A rotated or flipped PPTX group is still mapped as if unrotated, which is consistent with how each shape's own bounds are reported.
- Decisions: none new.
- Next task: the #56 follow-up (SilverDog's non-blocking notes), then #70 if the platform owner agrees to option 1.
- Warnings: the DOCX header/footer finding is SilverDog's, in `docx.py`. Don't fix it from this stream.

---

## Previous handoff

- Agent: Claude Code, working the DOCX issue queue at the human's request
- Date: 2026-09-28
- Branches: `fix/docx-font-and-section-resolution` (PR #71, fixes #49), `feat/docx-cantsplit-picture-rows` (PR #74, part of #55). Both based on main `9f58568` (after PR #69 merged).
- Objective: work the DOCX-owned issues left in CURRENT.md/BACKLOG.md after #69 merged.
- Completed: #44 closed with no code change -- checked against main and found already fixed by PR #67 (`mc:Ignorable` pruning, cell-ending-in-table) and the earlier #42 blank-lines work (empty header/footer); verified with the issue's own named regression tests before closing. #49: `_slot_fonts` now lets a `*Theme` w:rFonts attribute win over a stale literal one (ECMA-376 SS17.3.2.26 says the literal must be ignored, not just deprioritised); `theme_fonts` now also resolves `majorAscii`/`minorAscii`. `page_sizes`/`section_index` now share one `_section_breaks` walk that descends into `w:sdt/w:sdtContent` and never into `w:sectPrChange`, matching how `docs.py:printable_width` already read sections. #55 (first half only): `protect_picture_rows` adds `w:cantSplit` to a row that gained a picture from #34, skipped when the picture is already taller than the printable page; new `printable_height` alongside `printable_width`, sharing a new `_final_section` helper.
- Checks: both branches pass the full platform suite locally (285 passed, 8 skipped, 12 pre-existing failures reproducible on main with no changes -- a subprocess-parser environment issue in this checkout, unrelated). Ruff, format, mypy and bandit clean on both.
- Known failures: none caused by this work. The 12 pre-existing `test_docx.py`/`test_preflight.py`/`test_web.py` failures ("The file could not be analysed") are an environment issue in this checkout (a subprocess-based parser not finding something it needs), confirmed present on `main` before any of these changes -- not investigated further, out of scope for DOCX-owned issues.
- Unresolved: #55's second half (geometry-based assignment of a picture anchored outside its table, `picture_placement_uncertain` reporting) is a larger follow-up, left open and commented on the issue. #53 and #54 are untouched, both left for whoever's next.
- Decisions: none new.
- Next task: #54 (post-import blank-page repair) or #53 (post-import Docs API/PDF read-back, still blocked on the live OAuth scope spike) are what's left DOCX-owned. Review PRs #71 and #74 before merging (no independent DOCX reviewer per CURRENT.md -- worth flagging to whoever picks this up next).
- Warnings: do not assume a `test_docx.py` failure here is real without first checking it also fails on unmodified `main` -- the subprocess-parser environment issue produces the same 10-12 failures regardless of what's changed in this checkout.

---

## Previous handoff

- Agent: Claude Code / QuietHeron, working the issue queue at the human's request
- Date: 2026-09-23
- Branches: `fix/xml-element-limit` (#59, fixes #46), `fix/dangling-relationships` (#61, fixes #47, stacked on #59), `fix/pptx-font-rewrite-scope` (this branch, fixes #50). All based on main `6ae8dee`.
- Objective: the platform issues from the audit that don't touch the DOCX renderer, where SilverDog has #57 open.
- Completed: #46: XML elements counted during parsing, limit a setting (500,000), message names the limit. #47: a relationship to an absent part is reported, not fatal (a missing slide still is); resolution is case-insensitive. #50: the PPTX font rewrite touches only `<a:latin>` start tags, skips the symbol charset, and drops the stale PANOSE, pitch and charset. Closed the legacy Apps Script issues #1–#4 as not planned, at the human's request.
- Checks: each branch passes the platform suite locally (259 / 262 / 261 passed, 8 skipped); ruff, format, mypy and bandit clean.
- Known failures: none.
- Unresolved: PPTX still applies MEDIUM-confidence candidates automatically where DOCX applies HIGH only. That's the shared font service owner's decision (#27, `docs/publisher-font-audit.md`) and is not changed here.
- Decisions: none new.
- Next task: merge #59 before #61. DOCX issues #44, #48 and #49 are left for SilverDog. #36, #51, #52, #53, #54 and #55 remain.
- Warnings: agent-mail is still unavailable to this session (no registration token), so issues were claimed by GitHub comment instead.

---

## Previous handoff

- Agent: Claude Code / QuietHeron, standing in on DOCX at the human's request
- Date: 2026-09-23
- Branch: `fix/docx-blank-lines-and-text-check`, based on main `5510749`
- Objective: fix #42 (the empty-paragraph pass deleted every blank line, page-break paragraph and empty header) and #43 (the post-import text check reported missing text on most real documents).
- Files changed: `app/workspace_toolkit/docs.py` (`transform`, `remove_empty_paragraphs`, `source_text`), `tests/platform/test_docx_blank_lines.py` (new, 11 tests), coordination files.
- Completed: `transform` records which paragraphs were already empty before any pass, and `remove_empty_paragraphs` removes only paragraphs a pass emptied (for example by removing ink), never the last paragraph of a cell, header, footer or text box. `source_text` joins runs within a paragraph with nothing, separates paragraphs, tabs and breaks, skips `mc:Fallback` and `w:vanish` runs, and still treats a skipped field result as a word boundary.
- Checks: 241 platform tests pass, 8 skip (LibreOffice validity tests, as before); ruff, format, mypy and bandit clean.
- Known failures: none.
- Unresolved: hidden text applied through a character style is not resolved. Nothing here was run against live Google. The blank-page behaviour of kept separator paragraphs after import is #54's subject, not fixed here.
- Decisions: none new. The emptiness rule itself is unchanged; only which paragraphs it may act on.
- Next task: DOCX review by someone other than the author (CURRENT.md notes DOCX has no independent reviewer), then #44/#45.
- Warnings: agent-mail file reservation was not taken, because this session lost its agent-mail registration token.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-23
- Branch: `test/publisher-breadth`, based on main `135f744`
- Objective: parser breadth for the constructs PUB-001 lacks, built on what libmspub 0.1.4 actually emits rather than on assumed callbacks.
- Files changed: `native/pub-parser/src/collector.{h,cpp}`, `src/model.h`, `tests/test_libmspub_shapes.cpp` (new), `tests/test_collector.cpp` and `tests/test_text.cpp` (labels only), `CMakeLists.txt`, `packages/document-model/schema.json` (one description), `docs/publisher-parser.md`, coordination files.
- Completed: read libmspub-0.1.4's source and found it never calls `openGroup`, `startMasterPage`, the list callbacks, `openLink` or `insertField`; emits groups as layers; folds rotation and flips of everything but text into outlines; paints master content into every page; and calls `drawGraphicObject` only for BorderArt. The parser now classifies each layer at close (probable authored group, multi-pass wrapper, or clip wrapper), recovers rotation from rotated rectangular outlines instead of reading rotated pictures as masks, flags mirrored outlines, rotated fills and border-art tiles, and treats a bitmap-filled `drawRectangle` as rectangular (it was classed as a mask). 13 new tests; the unreachable ones are labelled.
- Checks: 105/105 C++ tests pass in CI (native job and container build); Python lint green. Not compiled locally: this machine has no C++ toolchain.
- Known failures: none in CI.
- Unresolved: **PUB-001 acceptance must be re-run locally.** Its test asserts its one layer is a wrapper; under the new rule it most likely still is, but that is unverified. If it reclassifies, record it, do not edit `expected.json` to match. Nothing here is verified against a real grouped, rotated, flipped, cropped or border-art `.pub`.
- Decisions: "a layer is never a group" superseded. See DECISIONS.md, 2026-09-23.
- Next task: the renderer-readiness gap report (now largely this table: groups inferred, master content duplicated per page, crops unapplied, border art as many images, lists/links unrecoverable), then the font audit. Stop before any Slides renderer code (PROJECT.md section 38).
- Warnings: the grouping rule is a heuristic from library source. Conservative by design: a false negative loses grouping, never content.

---

## Previous handoff

- Agent: Codex / SilentMountain
- Date: 2026-09-23
- Branch: `feat/shared-font-substitution`, based on main `68f9eab`
- Objective: create one reported font-substitution policy for PPTX, DOCX and PUB,
  with an education-focused mapping and PPTX application path.
- Changed files: shared fonts module; PPTX worker and Google upload path; platform
  tests; `docs/font-compatibility.md`; coordination files.
- Work completed: central AVAILABLE/SUBSTITUTED/UNKNOWN catalogue; exact Office
  metric alternatives; education/handwriting candidates; cautious accessibility
  recommendations; PPTX run and theme analysis; credential-free package rewrite;
  converted-package upload; structured occurrence reporting.
- Checks: 155 platform tests passed, 6 skipped; Ruff and formatting clean; mypy
  clean; 19 legacy Node regressions passed. A focused Google test proves the
  rewritten PPTX, rather than the source, is uploaded.
- Known failures: none in offline checks.
- Unresolved: Google Workspace font availability and visual fidelity need live
  validation; DOCX and Publisher integrations are assigned but not in this branch.
- Decisions: see 2026-09-23 font decision in `DECISIONS.md`.
- Next task: review and merge this branch, then let DOCX and Publisher consume
  the shared API and validate representative education resources.
- Warnings: Google Fonts catalogue membership is not a live Workspace guarantee.
  Do not auto-apply mappings marked `manualReview`; do not add font binaries.

---

- Agent: Claude Code
- Date: 2026-09-22
- Branch: `feat/docx-parser-renderer`, branched from `feat/platform-pptx-preflight` (PR #8). Must land after it.
- Objective: port the DOCX conversion knowledge onto the platform as a parser and Docs renderer per PROJECT.md section 4, then wire it through the web, job and Drive paths so a .docx converts end to end.
- Files changed: `app/workspace_toolkit/docx.py` and `docs.py` (new), `pipelines.py` (new registry), `package.py` (parameterised by format), `jobs.py`, `worker.py`, `web.py`, `google.py`, `static/app.js`, `static/index.html`, `tests/platform/test_docx.py` (new), README, docs/research.md, coordination files.
- Completed: legacy VML-only pictures rebuilt as inline DrawingML; headers and footers given the same structural passes as the body; anchor classification (text box, picture, ink, unsupported) with an explicit registry for groups, canvases, charts, chartex and SmartArt; intermediate model with bounds in points, per-section pages, fonts, compatibility and warnings; transform passes (mc:Fallback stripping, ink removal, background removal, anchor rewriting, conservative empty-paragraph removal); floating-table positioning from real anchor coordinates; backing pictures kept and pushed behind the text; package rewriting that preserves every other part byte-for-byte.
- Checks: 78 Python tests pass (39 existing + 39 new). Ruff check/format, mypy and Bandit clean; app.js syntax checked. Codex's PPTX path verified unaffected. Smoke-tested offline against four real Word worksheets: parser and renderer agree exactly on every one, producing 6/10/4/10 positioned tables with coordinates matching the source anchors. One document's 4 legacy VML-only pictures convert and no <w:pict> remains; its header and footer are now processed as story parts.
- Known failures: none in local checks.
- Unresolved: no real DOCX has been through a live Google conversion — every Google interaction is covered by a test double only. Backing-picture/behind-text handling is not exercised by any real sample (see DECISIONS). Google's z-ordering of a floating table over a behind-text picture is reasoned from Docs' own "Behind text" support, not observed.
- Decisions: see DECISIONS.md — DOCX supersedes "preserve src/"; rendering rewrites the package rather than calling the Docs API; Google honours w:tblpPr (verified); stdlib ElementTree over lxml; Package parameterised by format.
- Next task: wire DOCX into the web/job/Drive path so a file converts end to end, then run a real worksheet through it and compare against the Apps Script output, which is the current behavioural baseline.
- Warnings: do not prune `feat/docx-floating-tables` — it is the reference implementation for this port. Schema order is load-bearing in two places: CT_TblPrBase requires tblpPr and tblOverlap before tblW, and CT_Anchor requires any wrap element before wp:docPr. Getting either wrong makes Word reject the file. Do not add real school documents to Git.

---

## Previous handoff (Codex, platform and PPTX)

- Agent: Codex
- Date: 2026-09-22
- Branch: `feat/platform-pptx-preflight`
- Base: `origin/main` at `a145127`
- Objective: add the shared application foundation and first PPTX preflight/native-import workflow while preserving the Apps Script DOCX fixer.
- Files changed: coordination files; Python application under `app/`; platform tests; Docker/Cloud Run/CI configuration; dependency locks; `PROJECT.md`; `docs/platform.md`; `.gitignore`.
- Completed: bounded PPTX package inspection; text/font/asset/relationship/risk manifest; private extraction of embedded assets; Google OAuth state+PKCE flow; `drive.file` native import; private recovered-asset uploads; Slides count/size/text and image/table/chart count read-back checks; reports; temporary job cleanup; offline CLI; container and CI definitions.
- Checks: 48 Python tests and all 19 DOCX Node regression tests passed. Ruff, formatting, mypy, Bandit, pip-audit, secret scan and JavaScript syntax passed locally. GitHub CI previously passed its Linux container build/smoke test and will rerun for this update. Offline preflight passed against files generated by installed Microsoft PowerPoint: a two-slide 720 x 540 pt deck with 2 text boxes, 1 shape and 1 table; and a one-slide media deck with an image, WAV audio and editable caption. The media package yielded two PNG assets (the image and PowerPoint's audio preview) plus one WAV asset, with the audio timing reported as intentionally ignored. Validation artifacts remain outside Git.
- Known failures: none in local checks.
- Unresolved: no live OAuth/Google conversion; no real PPTX regression fixture; no visual fidelity check; no automatic repair/media reinsertion; no durable queue/idempotency for interrupted Google writes.
- Decisions: FastAPI stays separate from Apps Script; native Drive import renders PPTX; preflight provides evidence and warnings; user OAuth uses `drive.file`; documents and tokens are not stored centrally. See `DECISIONS.md`.
- Next task: continue deterministic parser and API-boundary fixtures. Create GCP test configuration only after the local codebase is ready.
- Warnings: do not edit this branch/worktree concurrently. Do not add credentials or real school documents to Git. A candidate `NATIVE` status is not verified compatibility. Google writes can leave private partial outputs after uncertain failures.
