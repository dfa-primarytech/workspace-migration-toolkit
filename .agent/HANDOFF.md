# Handoff

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
---

## Previous handoff

- Agent: Claude Code (second session, DOCX stream)
- Date: 2026-09-30
- Branch: `fix/docx-placement-sections`, the top of a stack on main `2d80316`: `fix/docx-page-size` (#114) <- `fix/docx-same-page-geometry` (#134) <- this (#112, #115, #116, #117, #118, #135). `fix/docx-textbox-ends-container` (#113) is on main by itself.
- Objective: fix the DOCX issues from the 2026-09-29 audit and Codex review, split with the Publisher session (which took #105-#111 on `fix/publisher-planning-crashes`).
- Files changed: `docx.py` (`twips`, `page_geometry`, `governing_sections`/`section_of`, `body_blocks`, margin strips in `anchor_position`, `on_an_unknown_side`), `docs.py` (`Sections`, per-section `printable_width`/`printable_height`/`_margin`, `_page_relation`, `_row_cells`/`_cell_at`, `_scale_extent`, `_end_with_paragraph`, `_gained_picture`; `transform` takes a fallback section for headers), tests `test_docx_page_size.py`, `test_docx_same_page.py`, `test_docx_textbox_container.py`, `test_docx_placement.py` (all new), `test_docx.py`, `test_docx_validity.py`, DECISIONS.md, this file.
- Completed:
  - #114: decimal and unit page sizes are read; an unreadable one is refused (`invalid_page_size`), never A4.
  - #134: the geometry pass needs a shown common page (DECISIONS.md, 2026-09-30); `picturesGeometryUncertain` now reaches the saved report.
  - #113: a text box's table no longer ends a cell, header, footer or body.
  - #135, #115: each table, row and placement is measured by its own section's current properties.
  - #112: margin strips are restated from the paper's edge; inside/outside keep today's reading and are counted in `positionsPageSideUncertain`.
  - #117: cells are found through the grid (gridBefore, gridSpan); a vMerge continuation is reported, not filled.
  - #116: a text box's own picture no longer releases its blank lines. #118: a group scales as a whole.
- Checks: the full stack, 540 platform tests passed, 14 skipped; Ruff and mypy clean. Every new test file was run against main: 33 of its 37 tests fail there (the other 4 guard behaviour that must not change).
- Known failures: none.
- Unresolved:
  - #113: whether Word rejects the old output is still unestablished; the new LibreOffice case runs only in CI.
  - #134: the three-block rule for documents without `w:lastRenderedPageBreak` is a judgement, not a measurement.
  - A picture inside a text box, floating in it, is still not inlined when the box becomes a cell (the parent map is stale by then); noticed while testing #116, not changed.
  - Headers and footers are measured by the body's last section; which sections use them is not worked out.
- Decisions: DECISIONS.md, 2026-09-30 (a shown common page; margin strips and page-sided frames).
- Also this session (platform, each its own PR on main, independent of the DOCX stack and of each other; a trial merge of all four with #144 passes 523 tests):
  - #133 (PR #147): docs/platform.md now gives the 3600 s request timeout and how the job and parser deadlines sit under it.
  - #120 (PR #148): `Google.request` retries GET/HEAD only, 3 attempts, Retry-After up to 30 s; writes are asked once.
  - #121 (PR #149): pipelines no longer upload the report; web.py saves it once, after the Drive, import-limit and pictures notes.
  - Filed #146 (a picture floating inside a text box stays floating in the new cell). Cross-reviewed the Publisher session's #138, #139, #140 and #145 (comments on each; no blockers).
  - Then, each its own PR on main (trial merges with every other open PR of mine are clean):
    #146 (PR #153, pictures decided after text boxes, with a fresh parent map);
    #119 (PR #156, font answers looked up by normalised name; the parent map kept in step with each box it moves);
    #122 (PR #157, `model.text_tokens` on both sides: autoText, runs joined within a shape, hyphen variants; a word holding `w:sym` is left out, not mapped);
    #125 (PR #158, validator: missing zIndex reported, self-parent reported);
    #123 (PR #159, comment and fixed status only; no test can fail on main, stated in the PR).
  - Then the native parser issues, handed over by the Publisher session; no local Linux build here, so each PR pushed its tests first and CI shows red, then green (run ids in each PR):
    #126 (PR #161, id-to-element map in documentJson; output unchanged);
    #127 (PR #162, covered cells share the cell cap; new maxTableRows);
    #128 (PR #163, graphic objects classified by the asset's settled MIME; metadata only);
    #129 (PR #164, top-level catch in main, exit 4, allocation-free last-resort report; PUBIR_FAIL_FOR_TESTING hook). Green in run 36713758504 and ready for review.
- Next task: the empty-drawing residue (#20) the #113 tests ran into. #150 is the Publisher session's (PR #160).
- Warnings: merge the stack in order (#114, #134, then the placement PR); after a squash merge, the next branch needs rebasing onto main. #113 conflicts with nothing in the stack.
