# Handoff archive

Older entries moved out of `HANDOFF.md` to keep that file to the most recent
few. Not required reading before starting work -- consult it only when you
need history older than what `HANDOFF.md` itself carries. Git log and merged
PR descriptions have the same detail in full.

---

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

---

- Agent: Claude Code / QuietHeron (platform)
- Date: 2026-09-28
- Branch: `feat/strip-video-for-slides`, based on main `1b5efa6`
- Objective: #36 step 2. Take embedded video out of a deck before it goes to Google, so large decks fit Slides' 100 MB conversion limit and upload faster.
- Files changed: `app/workspace_toolkit/pptx.py` (`strip_videos` and helpers, called from `render`; a `video_saved_separately` analysis warning), `google.py` (`videos_removed_warnings`, `conversion.videosRemoved`), `web.py` (import-limit warning judged on the converted file); `tests/platform/test_pptx_video.py` (new, 12 tests), `test_pptx_validity.py` (new, LibreOffice), `test_web.py` (one test); `.github/workflows/pptx-validity.yml` (new); `docs/platform.md`; this file.
- Completed:
  - **What is removed.** A video part goes if every relationship to it is a video or `p14:media` one. Its relationships, its `a:videoFile` / `p14:media` markup (and a `p:ext` / `p:extLst` / `p:childTnLst` left empty), and the `p:video` timing nodes that target its shape are removed too.
  - **What stays.** The picture element and its poster frame, so the slide shows a still image.
  - **How it's edited.** As bytes, like the font rewrite. Each edited part is re-parsed and checked: every picture must survive and no removed id may remain referenced. A part that fails the check keeps its video.
  - **Audio is untouched,** because transition sounds share the same relationships.
  - **Media copies keep their own name,** at the human's request: `<deck> – slide NN – <object name>.ext`. The analysis now records each object's `name` (`cNvPr`). PowerPoint names inserted media after its file, so a copy reads "Volcano eruption.mp4" rather than "video 3". Default names ("Picture 3", "Recorded Sound") fall back to the number. On a media object, the video or sound takes the name, not its poster image.
- Checks:
  - Platform 352 passed, 9 skipped (main: 334 and 8). The extra skip is the LibreOffice check, which runs in CI.
  - Ruff clean; mypy reports no issues in 17 files.
  - A reference-integrity test checks that every `r:*` attribute resolves and every internal target exists after stripping.
  - The import-limit test was confirmed to depend on stripping: without it, the converted deck is exactly the source size.
- Known failures: none locally.
- Unresolved:
  - "Slides does not import embedded video" is from `docs/research.md` and not observed live.
  - No real PowerPoint deck with video has been through this. The fixtures are hand-written in PowerPoint's shape, including the 2007 link-only form.
  - Orphan video parts (with no relationship to them) are not removed.
  - The Drive copy of a video is the only one the conversion makes once the video is stripped; `removed_video_not_saved` says so if it fails.
- Decisions: video is stripped unconditionally, not only for large decks, because Google drops it anyway.
- Next task: #36 step 3 (opt-in picture compression), which needs the human's sign-off and a UI choice.
- Warnings: `docx-validity.yml` says a skipped test fails the job, but its flags only report skips. The new `pptx-validity.yml` enforces it by checking the summary line. The DOCX workflow is the DOCX stream's and was not changed.

---

- Agent: Claude Code / QuietHeron (platform)
- Date: 2026-09-28
- Branch: `feat/no-upload-size-limit`, based on main `b5a116d`
- Objective: #36 step 1. The human wants no file size limit that staff can see: a "25 MB" line on the page made staff assume their files wouldn't convert.
- Files changed: `app/workspace_toolkit/config.py`, `package.py`, `jobs.py`, `worker.py`, `web.py`, `google.py` (`download`), `cli.py`, `server.py` (Hypercorn), `static/app.js`; `pyproject.toml`, `requirements.lock`, `requirements-dev.lock`; `deploy/cloud-run.example.yaml`; `docs/platform.md`; `tests/platform/test_preflight.py`, `test_web.py`.
- Completed:
  - **No upload limit by default.** `MAX_UPLOAD_SIZE` is optional and unset. The page shows no limit and the browser doesn't check size.
  - **Zip-bomb guards scale with the file.** One part may expand to 2x the file and the package to 3x, never below the old 50/200 MiB, which stay as floors.
  - **Time and memory allowances scale with the file:**
    - analysis: 30 s plus 1 s per 4 MiB;
    - job: 240 s plus 1 s per 512 KiB, capped at 3,300 s;
    - worker address space: 768 MiB plus 2x the file.

    A Drive-picked file's job allowance and the sign-in expiry check are applied again once its size is known.
  - **A file over Google's published import limit** (Docs 50 MB; Slides and Sheets 100 MB) gets a `beyond_import_limit` warning. It is not refused.
  - **Uvicorn is replaced by Hypercorn**, which speaks HTTP/2 without TLS (h2c). The deploy template sets the `h2c` port name and a 3,600 s timeout.
- Checks:
  - Platform 334 passed, 8 skipped (main: 324 and 8).
  - Ruff check and format clean; mypy reports no issues in 17 files; Bandit reports no issues; `pip-audit -r requirements.lock` finds no known vulnerabilities; `pip check` is clean for both lockfiles.
  - The real server (Hypercorn) was run locally with synthetic 111 MB and 332 MB decks over h2c (negotiated HTTP/2) and HTTP/1.1. All four uploads returned 200 in 16–59 s, with the import-limit warning. h2c was about a third slower than HTTP/1.1 on this Windows machine; that isn't measured on Linux and wasn't tuned.
- Known failures: none locally. The container build wasn't run here (no Docker on this machine); CI's container job is the check.
- Unresolved:
  - End-to-end HTTP/2 on Cloud Run is configured from Google's documentation and hasn't been observed live.
  - Google's import limits are the published figures and haven't been observed live.
  - The file is still uploaded twice (Check, then Convert). Keeping it between requests needs shared storage across instances.
  - Memory: at about 4x the file per job, two ~250 MB jobs on one 2 GiB instance would not fit. A 1 GB video deck needs about 4 GB.
- Decisions: size limits removed at the human's direction. Safety guards now scale with the file instead of being fixed.
- Next task: #36 step 2 (strip audio and video before Slides import, so large decks fit Google's 100 MB) and the memory setting for large files (4 GiB, or one job per instance).
- Warnings: PRs #72 (Excel) and #82 (branding) touch `web.py`, `jobs.py`, `package.py`, `worker.py` and `app.js`; expect small conflicts. `README.md`'s 25 MiB line describes the frozen Apps Script tool and was left alone.

---

Kept here: the most recent entries only. Older ones are in
`HANDOFF-archive.md` -- git log and merged PR descriptions already carry
that detail in full, so this file no longer needs to. Append your own entry
at the top; when this file holds more than 3, move the oldest into the
archive rather than growing this one further.

- Agent: Claude Code, working the DOCX/platform queue at the human's request
- Date: 2026-09-28 (later still)
- Branch: `feat/drive-picker-upload`, PR #81
- Objective: the human asked whether the tool could accept a file already in Drive, not just a local upload; then separately gave access to the project's real GCP project (`workspace-migration-toolkit`) to verify the result and the long-blocked #53/#54 scope spike live.
- Completed: Add from Drive (Google Picker) implemented and opened as PR #81 -- see that PR/CURRENT.md for the feature itself. Then run live against a real GCP project (Web OAuth client `wmt-local-dev-web`, Picker API key), which found and fixed two real bugs the reasoned design got wrong: a Website-restricted Picker API key breaks Picker (Picker's own requests don't carry this page's referrer -- restrict to the Google Picker API only), and a `drive.file` per-file grant needs `PickerBuilder.setAppId()` with the OAuth client's Cloud project number or a picked file downloads as unavailable even though Picker itself works (new `Settings.picker_app_id`, derived from the client ID's numeric prefix, no new config needed). Also found the CSP needed `style-src 'unsafe-inline'`, not just `script-src`/`frame-src`/`connect-src` -- gapi's picker widget sets inline styles directly on this page. Separately, and the more consequential finding: **`documents.get` and `files.export` (PDF) were confirmed reachable under `drive.file` scope on a Google Doc this app created** -- tested directly against the Docs/Drive APIs with a real access token on a real converted document. This is the exact spike #53's post-import-checks design and #54's post-import-repair design were both blocked on since September. Neither is implemented; this only removes the reason neither could start.
- Checks: 324 passed locally, 8 skipped, **0 failures** -- the 13 "pre-existing" failures this stream has been carrying since September turned out to be this checkout missing `pip install --no-deps -e .` (the editable install), not an unfixable environment issue; installing it for the live test made them all pass. Worth doing in any fresh checkout of this repo. Ruff, format, mypy and Bandit clean. `node --check` on app.js passes.
- Known failures: none.
- Unresolved: PR #81 needs review/merge. #53 and #54 themselves are still unimplemented, now unblocked. Visual fidelity (comparing a converted document's actual rendering to the source) is still unverified -- nobody has done that either, and it's #53's own stated point.
- Decisions: see DECISIONS.md, 2026-09-28 (two entries: the Picker/token-exposure tradeoff, and the live verification results).
- Next task: implement #53 (or #54) now that the spike is answered. Otherwise #36 or Codex's XLSX PR #72 are what's left.
- Warnings: the GCP project and OAuth client used here are real and billable in principle, though nothing beyond free-tier API calls was used. No credentials were committed; the OAuth client secret was read from a downloaded JSON file (never typed in chat) and the short-lived access token used for the two live API calls was pasted by the human from their own signed-in browser, not obtained by this session signing in (the assistant does not complete Google sign-in flows itself, even when asked). **If a fresh local OAuth client or API key is needed again, create a new one** -- don't assume the ones from this session are still valid or that their exact restrictions are correct for a different testing need.

---

- Agent: Claude Code / QuietHeron (platform)
- Date: 2026-09-28
- Branch: `fix/library-folder-race`, based on main `bde062a`
- Objective: #70. Two conversions at once could each create a "Workspace conversions" library folder. Implemented option 1 from the issue.
- Files changed: `app/workspace_toolkit/google.py` (`library()`, new `_libraries()`, `_library_lock()`, `Google.warnings`), `app/workspace_toolkit/web.py` (the convert route adds `google.warnings` to the report), `tests/platform/test_google.py`, `tests/platform/test_web.py`, this file and BACKLOG.md.
- Completed:
  - The search and create in `library()` now run under a lock, one per event loop (so one per process in production), shared by everyone's jobs.
  - After creating a library, the search runs again. If an older library turned up (made by another instance), that one is used, and a `library_duplicated` warning (IGNORED) goes into the report. Nothing is moved or deleted.
  - A failed re-check keeps the folder that was just made, rather than failing the job.
  - The warning is added in `web.py`, so PPTX and DOCX both get it without touching `docs.py` or `pipelines.py`.
- Checks: platform 308 passed, 8 skipped (main `bde062a`: 304 and 8). Ruff check and format clean; mypy reports no issues in 17 files; Bandit reports no issues. The two new behaviours were each checked by breaking them. With the lock swapped for a null context, the concurrency test fails; with the re-check disabled, the other-instance test fails. The unmodified code passes both.
- Known failures: none.
- Unresolved:
  - The re-check depends on Drive's search returning a folder created moments earlier. That hasn't been observed against live Drive; if search lags, a duplicate can still go unreported, as it did before.
  - Only the report returned to the page carries the new warning. The copy the PPTX and DOCX pipelines save to Drive is written before `web.py` sees it. Adding it there means a change inside each pipeline, and `docs.py` belongs to the DOCX stream.
- Decisions: none new; this is the issue's option 1.
- Next task: #70 needs review and the human's merge. #52 has no open items left.
- Warnings: the lock is per process. Cross-instance duplicates are detected, not prevented. Option 2 in #70 (keeping the library id in the session) would narrow that further.

---

- Agent: Claude Code, working the DOCX issue queue at the human's request
- Date: 2026-09-28
- Branch: `feat/docx-orphan-picture-geometry`, PR #77, part of #55's second half. Based on main after #76 merged.
- Objective: extend the orphan-picture placement pass beyond the single paragraph immediately above a table.
- Completed: `place_orphan_pictures` now walks every consecutive paragraph holding nothing but anchored pictures (or nothing at all) directly above a table, not just the last one -- a worksheet often gives each question picture its own paragraph. Stops at the first paragraph carrying real content. `_place_above` takes that paragraph list; the column/row matching itself is unchanged.
- Checks: 294 passed locally, 8 skipped, 13 pre-existing failures (same environment issue, confirmed on unmodified main). Ruff, format, mypy and Bandit clean.
- Known failures: none caused by this work.
- Unresolved: the fully general geometry case (arbitrary anchor position, `tblpPr`/`tblInd`, stated row heights, `picture_placement_uncertain` reporting) is still open on #55 -- most real worksheets lack the explicit positioning or row heights needed to compute a cell rectangle without guessing.
- Decisions: none new.
- Next task: #53/#54 still need a live Google test tenant to unblock. #36 (25MB upload limit) turned out to be a much larger platform/infra item (chunked uploads, object storage, background jobs, live Google limit verification) than its issue text suggests -- see the note added to the issue before picking it up expecting a quick fix.
- Warnings: same as always -- confirm any `test_docx.py`/`test_preflight.py`/`test_web.py` failure also happens on unmodified `main` before treating it as caused by your change.

---

- Agent: Claude Code, working the DOCX issue queue at the human's request
- Date: 2026-09-28 (later same day)
- Branch: `fix/docx-header-footer-manifest`, PR #76, split out of #52 (BACKLOG item 12). Based on main after #71/#74/#73 merged.
- Objective: the DOCX finding Claude 2 flagged back on #52 -- `docx.parse` counts anchors in `document.xml` only, while `render` also transforms headers and footers, so the preflight report can under-count.
- Completed: `parse()` now scans every header/footer part too, via a shared `_element_pairs` helper factored out of the body loop so both paths build identical element shapes. They can't be attributed to a numbered page (a header/footer's page range isn't computed by this model), so they land in a new `headerFooterElements` list naming their source part. `analysis_report()` -- the actual reviewer-facing summary -- now folds those into its element counts and warnings too, tagged with the part instead of a page index.
- Checks: 290 passed locally, 8 skipped, 13 pre-existing failures (confirmed present on unmodified main -- a subprocess-parser environment issue in this checkout, not this change; later traced to a missing editable install, not the checkout itself -- see HANDOFF.md's 2026-09-28 "later still" entry). Ruff, format, mypy and Bandit clean.
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
