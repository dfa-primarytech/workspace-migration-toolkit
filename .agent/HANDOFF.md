# Handoff

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

---

## Previous handoff

- Agent: Claude Code (Claude 1, platform/Publisher)
- Date: 2026-10-01
- Branch: `docs/handoff-macros`, based on main `29907e9`. All my PRs are merged: #185, #186, #187, #189.
- Objective: a real nursery workbook whose formulas broke in Google, and its macros. The owner asked for macro workbooks to convert, with the macros working in Google.
- Files changed:
  - #185: `sheets.py` (after import, `batchUpdate` sets locale `en_GB` and the person's time zone from `X-Time-Zone`, else Europe/London); `xlsx.py` (text-date note); `static/app.js` ("Not converted" row for a report with nothing to open; plain words for "Failed to fetch"); `web.py`, `pipelines.py` (`needs_time_zone`). Tests `test_sheets_locale.py`, `test_page_results.py`, `results_harness.js`.
  - #186: new `vba.py` (bounded MS-CFB reader, MS-OVBA decompression, module sources); new `apps_script.py` (rule-based translator for recorded macros: select, autofill, values, formulas, copy/paste, insert/delete rows/columns/cells, font, fill, MsgBox; anything else is copied as a comment and counted); new `macros.py` (`macro_free` rewrites `.xlsm` as `.xlsx`, as Drive imports no `.xlsm`; `prepare` writes `result/macros/`); `xlsx.py`, `sheets.py` (uploads `converted.xlsx`; saves "Macros – original Excel VBA.txt" and "Macros for Google Sheets (Apps Script).txt" in the folder). Test `test_vba_macros.py`.
  - #187: `auth.py` (optional `script.projects` scope; session `scripts`); new `script_projects.py` (`attach`: a bound project on the Sheet, manifest with `spreadsheets.currentonly`, `script.container.ui` and `sheets.macros`, so the macros show under Extensions → Macros); `sheets.py` (`add_macros`, `macro_notice`: `report["notice"]`, the one note shown on screen); `static/app.js`, `style.css` (the notice under the row). Test `test_script_projects.py`.
  - #189: new `buttons.py` (each worksheet shape's sheet, anchor, label and assigned macro; `link`: the assigned macro, or the only macro when the label begins with its name in whole words); `apps_script.py` (`_linker`: `onOpen` sets `Drawing.setOnAction`, leaving linked drawings alone); `macros.py` (`button_notes`: `macro_buttons_linked`, `macro_buttons_not_linked`); `sheets.py` (notice adds "Its button works too."). Test `test_macro_buttons.py`.
- Completed:
  - Live, on the owner's real workbook (#189 too: its button runs its macro): it converts in one step, no `#VALUE!` left (dates typed as text now read as UK dates), the macro attached and runs from Extensions → Macros, the notice shows. The owner confirmed ("works like a charm").
  - Apps Script API enabled on the Google Cloud project. Each person must also turn it on at script.google.com/home/usersettings; without it the report says `macros_not_attached` (`setting_off`) and the script stays as a text file in the folder.
- Checks: 772 platform tests pass on main after #189; Ruff, mypy and the secret scan clean. Test container runs the #189 code (same as main `29907e9`).
- Known failures: none.
- Unresolved:
  - Macro buttons (#189) work live: the owner's "Repair Columns" button runs `Repair`. But not on the very first open of the new Sheet; it did after the owner opened it again. Likely the Sheet opened before the script was attached. If it recurs, the notice should say to reload once, or a one-off "Turn on buttons" macro could link them with full authorisation.
  - Only recorded-style macros translate. Hand-written VBA (loops, variables, UserForms, events) is kept as comments and reported as `macros_partly_translated` / `macros_not_translated`.
  - The new scope means everyone already signed in sees a consent screen again on next sign-in.
- Decisions: DECISIONS 2026-10-01: macro workbooks convert (supersedes 2026-09-28); macros attached when allowed; one note on screen for macros; buttons run their macros.
- Next task: none claimed.
- Warnings:
  - Copies of the owner's nursery workbook (children's details) are in their Drive from the live test. Never put its contents, names or dates in issues, PRs or tests; the tests use synthetic workbooks.
  - The test host's gcloud needs `gcloud auth login` now and then (organisation reauthentication policy) before the picture token can be renewed.
