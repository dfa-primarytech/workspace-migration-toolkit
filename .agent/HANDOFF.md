# Handoff

- Agent: Claude Code (Claude 2, DOCX/platform/parser)
- Date: 2026-09-30
- Branch: `fix/docx-table-position`, based on main `f7f39c5` (PR #169). Before it: #167 (#55), merged.
- Objective: #168, pictures above an indented, aligned or floating table were measured against columns starting at the text column's edge. Then #53 and #54, in that order, one PR each (split agreed with Claude 1, who has #104, #88 and #36).
- Files changed: `docs.py` (`_table_start` reads `tblpPr`, `jc` and `tblInd`; `_place_above` offsets its column edges by it, and leaves and reports the stack when it's None); `tests/platform/test_docx_table_position.py` (new, 9); this file.
- Completed:
  - #168: an indented (`tblInd` in twips), centred, right-aligned (`jc`) or floating (`tblpPr` against margin, text or page) table has its columns where it says. An aligned floating table (`tblpXSpec`), a non-twip indent, a floating table that's also indented, an aligned table on an unstated page, or `bidiVisual` leaves the pictures and counts them under `picturesGeometryUncertain`.
  - 8 of the 9 new tests fail on main; the ninth guards a table at the text column's start.
  - Earlier, #55 (#167): `_place_above` needs the whole picture inside one column, straddlers are reported, and both passes' uncertain counts add up with each picture counted once.
- Checks: 630 platform tests passed, 17 skipped; Ruff clean; mypy clean.
- Known failures: none.
- Unresolved: `tblInd` is read as ECMA-376 states it, to the table's leading edge. Word's pre-2013 layouts put that edge a cell margin further left, which isn't modelled (nor was it before). A multi-column section's "column"/"text" frame is still read as the text column's start.
- Decisions: none new.
- Next task: #53 (post-import read-back, Docs first; report only, never on screen; fake Google in tests; new functions only in `google.py`, and tell Claude 1 before editing an existing one), then #54 (optional blank-page repair built on #53).
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
