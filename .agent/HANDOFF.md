# Handoff

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

## Previous handoff

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
