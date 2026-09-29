# Handoff

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

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-28
- Branch: `feat/publisher-renderer`, based on main `bb9cd61` (#90 merged)
- Objective: Publisher step 2 of 4. The renderer: IR → Google Slides API requests, offline.
- Files changed:
  - `app/workspace_toolkit/units.py` (new: lengths, frames, the Slides transform);
  - `publisher_art.py` (new: pictures Slides can take, drawn paths, composed border art);
  - `publisher_slides.py` (new: `plan`, `bind`, `check`);
  - `tests/platform/test_publisher_slides.py` (new, 38 tests);
  - `docs/publisher-renderer.md` (new), DECISIONS.md, this file, HANDOFF-archive.md.
- Completed:
  - Every IR element type has a mapping and a report line. See the table in `docs/publisher-renderer.md`.
  - Pictures carry a key until `bind()`; `keys_for(page)` lets step 3 sign links a page at a time.
  - `check()` refuses a plan Google would refuse: unknown requests, bad or duplicate IDs, use before creation, text ranges outside the text, unbound pictures.
- Checks:
  - Windows: 418 passed, 13 skipped. Linux (the human's Docker host, as the app user, with PUB-001 supplied): 421 passed, 10 skipped, including the PUB-001 plan test.
  - Ruff, mypy, bandit and the secret scan are clean.
  - **PUB-001:** 272 requests, no `check()` problems, pictures within 0.0001 pt of their frames. Status counts: 13 NATIVE, 7 SUBSTITUTED, 2 IGNORED. An offline drawing of the plan matched LibreOffice's rendering of the file.
- Known failures: none.
- Unresolved (all for step 3 or 4, and all unverified against Google):
  - whether `presentations.create` keeps an A5 page size (§14);
  - Google's text insets;
  - default table borders;
  - whether a 0.01 pt-tall line is accepted.
- Decisions: DECISIONS.md, 2026-09-28 (renderer defaults).
- Next task: step 3. Upload each page's pictures to the bucket, sign 15-minute links, `bind`, send, delete, then read the presentation back and report. The human creates the bucket and the signing permission; document the steps for them.
- Warnings:
  - Four PUB-001 pictures are heavily stretched. The reader drops Publisher's crops, and LibreOffice shows the same stretching. They are reported, not fixed.
  - The test host holds `/root/wmt-test/private/pub-001.pub` (the real booklet, mode 644 so the container user can read it) and its parsed bundle. Remove both when the Publisher work is finished.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher and platform)
- Date: 2026-09-28
- Branch: `feat/publisher-check-file`, based on main `c687cd2`
- Objective: Publisher step 1 of 4. The human approved the §38 stop point; decisions are in DECISIONS.md. A `.pub` can now be checked in the app.
- Files changed:
  - `Dockerfile` (parser build stage, runtime libs, binary);
  - `app/workspace_toolkit/publisher.py` (new);
  - `package.py` (`PUB` format, MIME aliases);
  - `pipelines.py` (`.pub` entry, `convertible`);
  - `config.py` (`publisher_parser`);
  - `jobs.py`, `worker.py`, `web.py` (convert refused up front);
  - `fonts.py` (run-together Sassoon names → Andika);
  - `static/index.html`, `app.js`;
  - `tests/platform/test_publisher_app.py` (new, 15 tests);
  - `docs/platform.md`, DECISIONS.md, this file.
- Completed:
  - The app image builds and ships the parser.
  - The worker runs the parser under a hard timeout, and "Check file" reports pages, page size, elements, pictures, fonts and warnings.
  - Each parser refusal is given in plain words.
  - Convert is hidden for `.pub` and refused before the upload.
- Checks:
  - Windows: 381 passed, 12 skipped. Linux (the human's Docker host, non-root, full suite): 383 passed, 10 skipped, including the hang test.
  - The app image built on the host; the parser's C++ tests passed 107/107 on the Debian base, and `publisher-parser --version` runs in the final image.
  - In the running image (capped, no network), the real parser refused a plain-text `.pub` and a non-Publisher OLE file as `unsupported_document`. Convert returned 501 `not_convertible`. The container used 48 MiB.
  - Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - ~~No real `.pub` has been through the app yet.~~ Done after the PR opened: PUB-001 was checked in the app image on the host. It took 0.56 s through the worker, reported 4 pages, and mapped Sassoon to Andika (see #90).
  - Parser warnings are technical, parser-facing text. Worth rewording once real files show which ones staff actually see.
- Decisions: see DECISIONS.md, 2026-09-28 (Publisher).
- Next task: step 2, the renderer (IR → Slides API requests, tested offline).
- Warnings:
  - `pipelines.py` is listed as the DOCX stream's. This change only adds an entry and a `convertible` flag.
  - The test host keeps `/root/wmt-test` and the `wmt-test/app:pub1` image for the next steps.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (platform)
- Date: 2026-09-28
- Branch: `feat/compress-pictures`, based on main `706a84c`
- Objective: #36 step 3. An opt-in "Make pictures smaller", for image-heavy files that stay over Google's limit once video is out.
- Files changed:
  - `app/workspace_toolkit/pictures.py` (new);
  - `worker.py` (runs it after render when asked; never fatal);
  - `jobs.py` (`compress_pictures` passed through; allowance doubled);
  - `web.py` (`X-Compress-Pictures` honoured on convert only; `pictures_report`; the over-limit warning names the option);
  - `static/index.html`, `app.js`, `style.css` (the checkbox);
  - `pyproject.toml` and both lockfiles (Pillow 12.3.0);
  - `tests/platform/test_pictures.py` (new, 15 tests), `test_pptx_validity.py` (a second LibreOffice check), `test_web.py` (stand-ins accept the new option);
  - `.github/workflows/pptx-validity.yml` (also triggers on `pictures.py`);
  - `docs/platform.md`; this file.
- Completed:
  - **What it does, to the converted copy only:**
    - pictures in plain picture frames (PowerPoint and Word alike) are resized to their drawn size at 220 ppi, allowing for crops;
    - PNG photos become JPEG, with the part renamed and its rels and content types updated.
  - **What it leaves alone:** anything it can't be sure about. See `docs/platform.md` for the list.
- Checks:
  - Platform 368 passed, 10 skipped (main: 353 and 9). The extra skip is the new LibreOffice check, which runs in CI.
  - Ruff clean; mypy reports no issues in 18 files; `pip-audit -r requirements.lock` finds no known vulnerabilities.
  - A test found a real bug before commit: the resize scale took the smaller of the two needs, so a cropped or stretched picture dropped below 220 ppi on one side. Now fixed; the test fails with the old rule.
  - Local LibreOffice 26.8 on the realistic fixture with a 3000x1688 PNG photo swapped in: after stripping and compression the package went from 7.0 MB to 0.1 MB, and the picture became a 1320x743 JPEG (6 in x 220). Both original and result render 2 slides with their text and the picture on slide 1.
- Known failures: none.
- **Found on the way, and fixed.** CI failed three new tests on Linux only.
  - Reproduced on the human's Docker host (a capped container of its own, labelled `wmt-test`).
  - Cause: `test_fonts.py` ran `worker.main()` in the pytest process, which applied the worker's OS limits to the test runner for good. Every later worker then inherited a 768 MiB hard address-space cap, and since #84 a worker asks for 768 MiB plus 2x the file. A process cannot raise a hard limit, so `setrlimit` failed and surfaced as `parse_failed`.
  - Fixes:
    - `worker.limit()` never asks above an inherited hard limit. This was latent in production too: a container started with tight limits would have failed every file.
    - The font test no longer caps the runner.
    - New Linux-only test: a worker under a stricter inherited limit still runs. It fails without the fix.
  - Result on Linux, full suite as a non-root user: 369 passed, 10 skipped.
- Unresolved:
  - No real image-heavy school file has been through this. Worth judging picture quality by eye on the first one.
  - Google's handling of the renamed `.jpeg` parts is not observed live.
  - Pictures inside groups and shape fills are never compressed. That could matter for some decks, but it can't be measured safely.
- Decisions: opt-in, off by default, and only on convert.
- Next task: #36 is complete in design terms; close it once someone has run a real large file end to end.
- Warnings: Pillow is new to the image. Its decompression-bomb limit is set per call (60 MP), in the worker.
