# Handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/Publisher)
- Date: 2026-10-06
- Branch: `fix/publisher-empty-table-cells`, based on main `c6689e2` (#193, deployed). Not merged.
- Objective: the school's 28-page Publisher booklet came out of Slides with tables running over each other and off the page.
- Files changed: `publisher_slides.py` (`_blank_cell_style`, `_blank_cell`; `deleteText` added to `KNOWN` and to `check`), new `tests/platform/test_publisher_table_cells.py`.
- Completed:
  - Cause: 30 of 45 cells in one table were empty tick boxes. Publisher stores no font for an empty cell; Slides sets an unstyled one in 18 pt, so every row was about 31 pt tall, not the planned 20.5 pt, and a table planned at 307 pt came out near 450 pt.
  - Fix: an empty cell is given the font and size most of its table's text uses (scaled as the text is), by putting a space in, styling it and deleting it.
  - Tested against the real Slides API: styling an empty cell directly is refused ("The object has no text"), so that route was dropped before shipping. With the space in and out, rows render about 23 pt. Page 19 of the booklet was replayed, old plan against new, onto scratch decks (290 requests accepted): the table's rows are visibly shorter. The scratch decks and the temporary sign-in are gone.
- Checks: 817 platform tests pass; Ruff, format, mypy and the secret scan clean.
- Known failures: none.
- Unresolved:
  - Only page 19 was replayed. Pages 20, 21 and 5 (overlapping tables, a table running off the page) should improve for the same reason; they need a real conversion to confirm.
  - Text still made 75% smaller on 11 tables (pages 5, 9, 19, 20, 21, 24, 27) and may overflow; not touched.
  - Tables' borders are Publisher's default grid (the file stores none).
- Decisions: none new.
- Next task: none claimed.
- Warnings: the booklet is the owner's file; it lived on the test host only while testing and was removed. A request Google refuses fails a whole page, so any new request kind is tried against the live API first.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/Publisher)
- Date: 2026-10-06
- Branch: `feat/publisher-wmf-pictures`, based on main `77c46c3` (#192, deployed to Cloud Run that day). Not merged.
- Objective: a school's 28-page Publisher booklet converted to Slides badly. Its clipart was missing.
- Files changed: new `app/workspace_toolkit/metafile.py` (a bounded WMF renderer: filled polygons, polypolygons with holes, rectangles, ellipses, solid brushes, plain pens; refuses a metafile needing text, a bitmap or an arc); `publisher_art.py` (`_open` draws a WMF); new `tests/platform/test_metafile.py` (metafiles built in code).
- Completed:
  - The booklet's six WMF pictures (pages 16 and 17) were `UNSUPPORTED: picture-missing`; they now convert (0 unsupported). Drawn and looked at: clipart illustrations, correct way up. A negative window extent (Publisher's own) was the bug the first run found; there is a test for it.
  - Run through the container with this branch: 28 pages, status counts NATIVE 130, SUBSTITUTED 155, IGNORED 96, FLATTENED 2.
- Checks: 814 platform tests pass; Ruff, format, mypy and the secret scan clean.
- Known failures: none in the code. Not checked in Google.
- Unresolved, all on the same booklet and all unseen in Slides:
  - 29 tables over 12 pages. 11 had their text made 75% smaller and may still overflow (pages 5, 9, 19, 20, 21, 24, 27); 21 narrow columns were widened (pages 10, 12, 16, 17, 19 to 21, 24). Borders are Publisher's default grid, as the file stores none.
  - 74 shapes are drawn as separate lines.
  - What the teacher meant by "a lot of pages to redo" needs the converted deck or screenshots next to the original.
- Decisions: none new.
- Next task: none claimed.
- Warnings: the booklet is the owner's file, kept on the test host only and removed afterwards; never put its contents in issues, PRs or tests. The test image `wmt-test/app:wmf` on the test host is from this branch; `wmt-test/app:main` is main `77c46c3`.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/DOCX)
- Date: 2026-10-06
- Branch: `fix/docx-page-sized-textbox-order-width`, based on main `8f45ba5`. Not yet a PR.
- Objective: school forms drawn as one page-sized text box, converted in the app, lost their right-hand side, came out in the wrong order, and lost their frame. The owner supplied 27 such Word files and 9 converted PDFs. Nothing from them is in the repo.
- Files changed:
  - `app/workspace_toolkit/docs.py`: `fit_tables_to_page` measures a floating table against the room from its left edge to the paper's edge (`_room_to_page_edge`), not the margins, and brings tables nested in a narrowed floating table down to their cell (`_fit_nested_tables`). `_replace_textbox` keeps boxes from one paragraph in the order written (`placed`). A small box inside a page-sized box in the same paragraph goes into that box's table as its own row, down the page where it was, lifted to end above the bottom margin (`_panels_in_page_boxes`, `_carry_panels`). A box's outline becomes the table's border (`box_outline`; white counts as none) and its stated text anchor sets the cell alignment (`box_vertical_align`).
  - `tests/platform/test_docx_page_textbox.py` (new, synthetic content only).
- Completed:
  - Each fix failed first, with the real symptom: a 9026-twip wrapper over a 10093-twip table; boxes in reverse order; the panel as a second table.
  - Run over all 27 forms: every one is a single table, and Word counts the same words as in the original.
- Checks: 802 platform tests pass; Ruff, format, mypy and the secret scan clean.
- Known failures:
  - Not verified in Google. Word was the stand-in, and it lays each form over 2 to 5 pages where the original is one. A form's content is taller as table rows than as a text box, so the foot panel falls onto a second page. Tried and ruled out: row heights, bottom-margin room, a blank first paragraph, matching page margins to the frame (best case 2 pages).
  - The converter leaves empty `<w:drawing />` runs where boxes were (#20). Word refuses to open the rewritten file for them; Google accepts it. Only the Google import has been shown to work.
- Unresolved:
  - Convert one form through the app and check the Google Doc: right side, order, frame, the foot panel, page count.
  - Whether to shrink the content to make a one-page form (not done: it changes the author's formatting).
- Decisions: DECISIONS 2026-10-06.
- Next task: none claimed.
- Warnings:
  - The 27 forms and their converted PDFs hold children's names, dates of birth and assessment data. They are in the owner's Downloads folder, not here. Never put their contents in issues, PRs or tests.
  - Tests that print a rewritten file's text must not run on those files.
  - The host test image `wmt-test/app:main` was rebuilt from main `8f45ba5` on 2026-10-02. It does not hold this branch.
