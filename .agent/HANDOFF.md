# Handoff

- Agent: Claude Code (Claude 2, DOCX/platform/parser)
- Date: 2026-09-30
- Branch: `fix/docx-straddling-pictures`, based on main `7eaf26a` (PR #167)
- Objective: #55's remaining criterion: a picture straddling two table columns was moved into one, chosen by its centre, and could then shrink.
- Files changed: `docs.py` (`_place_above` needs the whole picture inside one column; `place_orphan_pictures` counts `picturesGeometryUncertain` and hands those anchors to `place_pictures_by_table_geometry`, which skips them; `transform` adds the two passes' uncertain counts instead of keeping only the second); `tests/platform/test_docx_straddling.py` (new, 5); `test_docx.py` (one test's margin corrected); this file and the archive.
- Completed:
  - A picture that overlaps a column but fits none is left floating and counted as uncertain. The rest of its stack is left too (rows are read from the whole stack) and counted unplaced. A picture clear of the table is unplaced, as before.
  - Margin-strip anchors are covered: `_offset` already restates them from the paper's edge (#143).
  - A picture both passes see is counted once.
  - `test_a_page_relative_offset_is_measured_from_the_margin_not_the_paper` used a 457200 EMU margin against the section's 914400; it passed only through the centre rule. Corrected; it passes on main too.
  - 4 of the 5 new tests fail on main; the fifth guards that a picture inside one column is still placed.
- Checks: 621 platform tests passed, 17 skipped; Ruff clean; mypy clean.
- Known failures: none.
- Unresolved: `_place_above` measures columns from the text column's start and ignores a table's own `tblpPr` position or `tblInd`, so a floating or indented table's columns are misread there (the geometry pass does read `tblpPr`). Not changed here; worth an issue if it matters on real worksheets.
- Decisions: none new; this applies the geometry pass's existing containment rule to the earlier pass.
- Next task: none claimed. The live check on #166 (PUB-001, PUB-002, a real DOCX and PPTX through the test host) needs the owner.
- Warnings: the scratchpad venv's `.pth` points at `wmt-docx-fixes/app`, and the worker subprocess gets a fixed environment without `PYTHONPATH`, so tests run from another checkout convert with this checkout's code.
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
---

## Previous handoff

- Agent: Claude Code (Publisher)
- Date: 2026-09-30
- Branch: `fix/publisher-mask-budget`, stacked on `fix/publisher-page-failures` (PR #139, itself on #138): merge #138, then #139, then this
- Objective: #111, shape drawing's supersampled masks passing any memory bound.
- Files changed: `publisher_art.py` (`MASK_BUDGET`, `_supersample`); `tests/platform/test_publisher_masks.py` (new, 6); `docs/publisher-renderer.md`; this file.
- Completed: a coverage mask is drawn at 3x only while it stays within 40M pixels, else 2x, else 1x. The picture's own size is unchanged. A page-sized A5 shape keeps 3x. Mask sizes are tested by recording them, not by allocating a huge one.
- Checks: 532 platform tests passed, 14 skipped; Ruff clean; mypy only reports `hypercorn` missing locally.
- Known failures: none.
- Unresolved: the finished RGBA picture can still be 25M pixels (about 100 MB, and briefly two of them while compositing). That is Slides' own limit and not changed here. No out-of-memory crash was ever reproduced (Codex's qualification).
- Decisions: none new.
- Next task: all the Publisher audit issues are now fixed or in PRs. Next, the unclaimed Platform/PPTX ones (#120, #121, #124, #130-#133, #136, #137): claim them first.
- Warnings: none new.
