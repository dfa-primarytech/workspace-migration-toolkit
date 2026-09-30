# Handoff

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
---

## Previous handoff

- Agent: Claude Code (Publisher)
- Date: 2026-09-30
- Branch: `fix/publisher-planning-crashes`, based on main `2d80316`
- Objective: fix the high-priority Publisher audit issues #105, #106, #107 and #110 (claimed on each issue).
- Files changed:
  - `units.py` (`Frame.corners` no longer goes through `transform`);
  - `publisher_slides.py` (`_image` refuses a picture with no area; `_shape` hands a flat rectangle/ellipse to the new `_flat`; `group_all` checks kinds at every depth and counts WordArt's wrapper; `_wordart` cleans its text; `_text` reports pictures set in a text box);
  - `publisher_inline.py` (`marks` reads a text box's own `paragraphs`);
  - `tests/platform/test_publisher_planning.py` (new, 12);
  - `docs/publisher-renderer.md`, this file.
- Completed:
  - #105: a zero-height or zero-width element no longer crashes planning. A flat rectangle/ellipse is drawn as the line it looks like; a picture with no area is reported, not drawn.
  - #106: a table inside a nested group stops every enclosing group being made.
  - #110: WordArt inside an authored group is grouped; a control character in WordArt text is dropped instead of failing `check()`.
  - #107: U+FFFC in text boxes is now counted, so a picture there can't be taken for a table's. A recovered text-box picture is reported as missing on its box (`inline-picture-missing`), not placed: its position in the text isn't known.
  - All 12 new tests fail on main and pass here.
- Checks: 519 platform tests passed, 14 skipped; Ruff clean. Mypy reports only `hypercorn` missing from the local venv (`server.py`, untouched). Pillow 12.3.0 (the pinned version) is now installed in the local `.venv`, so the Publisher tests run locally.
- Known failures: none.
- Unresolved:
  - #107: placing text-box inline pictures properly would need their position in the laid-out text.
  - Not live-verified against Slides.
- Decisions: none new.
- Next task: #108, #109, #111 (Publisher). A second Claude session is taking the DOCX issues (#114, #134, #113, then #55/#112/#115/#117/#135); don't edit `docx.py`/`docs.py` from here.
- Warnings: none new.
