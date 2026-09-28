# Handoff

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
