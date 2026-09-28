# Handoff

Kept here: the most recent entries only. Older ones are in
`HANDOFF-archive.md` -- git log and merged PR descriptions already carry
that detail in full, so this file no longer needs to. Append your own entry
at the top; when this file holds more than 3, move the oldest into the
archive rather than growing this one further.

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
- Checks: 290 passed locally, 8 skipped, 13 pre-existing failures (confirmed present on unmodified main -- a subprocess-parser environment issue in this checkout, not this change). Ruff, format, mypy and Bandit clean.
- Known failures: none caused by this work.
- Unresolved: #53 and #54 are both explicitly design-only and blocked on the live OAuth scope spike in #53 (no GCP access in this environment, so neither can responsibly be built yet). #55's second half (geometry-based orphan-picture placement) is still open, left as a larger follow-up per the previous handoff entry.
- Decisions: none new.
- Next task: #53/#54 need someone with a live Google test tenant to unblock the scope spike first. Until then, #55's second half or #36 (25MB upload limit) are the remaining unblocked DOCX/platform work.
- Warnings: same as before -- don't assume a `test_docx.py`/`test_preflight.py`/`test_web.py` failure here is real without checking it also fails on unmodified `main` first.
