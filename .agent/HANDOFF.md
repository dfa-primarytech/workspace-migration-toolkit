# Handoff

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
- Next task: #150; then the native parser issues (#126-#129) if a Linux build is available. Claude 2 has #119, #122, #123, #125 and #146. `pptx.py`/`pictures.py`/`package.py` are Platform-owned: say so if the Platform stream is active.
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
---

## Previous handoff

- Agent: Claude Code (Publisher)
- Date: 2026-09-30
- Branch: `fix/publisher-page-failures`, stacked on `fix/publisher-planning-crashes` (PR #138): merge that first
- Objective: #108 (one failed picture upload blanked every later page) and #109 (leading tabs in a list shifted every text range).
- Files changed:
  - `publisher_convert.py` (`Delivery`, `undelivered`; `build_page` marks a picture it can't send; the page loop also catches `ToolkitError`; the outer handler catches `httpx.HTTPError`; neutral `pages_failed` wording);
  - `storage.py` (`Credentials.token` and `MetadataCredentials.email` raise `picture_delivery_failed`; `Bucket.delete` never raises);
  - `publisher_slides.py` (`_without_leading_tabs`, used by `_laid`);
  - tests: `test_publisher_convert.py` (+6, and a `store_fails` switch on the fake Google), `test_publisher_lists.py` (+1);
  - `docs/publisher-renderer.md`, this file.
- Completed:
  - #108: a picture that can't be stored or signed becomes a marked box (`pictures_not_sent`), and later pages are still made. After 3 failures in a row the bucket isn't asked again. A page that fails another way is left blank and reported, and the rest carry on. Metadata-server errors are reported properly instead of escaping as `httpx` errors.
  - #109: a list paragraph's leading tabs are dropped before any range is counted, so bullets and styles line up with the text Google keeps.
  - All 7 new tests fail on main and pass here.
- Checks: 526 platform tests passed, 14 skipped (with #138 underneath); Ruff clean; mypy only reports `hypercorn` missing locally.
- Known failures: none.
- Unresolved:
  - #108's PPTX/Sheets half (`Google.upload` not wrapping `OSError`, `json.loads(render.json)`) is Platform-owned and not done here.
  - #109 isn't live-verified; nesting by tabs isn't supported (Publisher's indent is set from its own margins).
- Decisions: none new.
- Next task: #111 (mask size cap), then the unclaimed Platform/PPTX audit issues.
- Warnings: none new.
