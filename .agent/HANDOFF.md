# Handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/UI)
- Date: 2026-11-24
- Branch: `whats-new-page`, based on main `a32de2a`.
- Objective: a page on the converter where staff can see what has been fixed or added, to check whether their problem is gone.
- Files changed: new `patch_notes.py` (the entries, newest first, in plain words; `render()` builds the page with everything escaped), `web.py` (public `/whats-new` route), `static/index.html` (footer link), `static/style.css` (kind badges), `AGENTS.md` (rule: a change staff can see adds an entry in the same PR). `test_patch_notes.py` (5 tests: public, linked, newest-first and valid kinds, no client or ticket names, escaping).
- Checks: 982 platform tests pass; Ruff, format, mypy clean. Not yet looked at in a browser.
- Unresolved: not deployed. The reports folder `Newbald 658976 converted - reports` could not be trashed with the Drive connector (no permission); the owner removes it in Drive.
- Next task: none claimed.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/Publisher)
- Date: 2026-11-23
- Branch: `badge-text-clear-of-pictures`, based on main `2f8947a`.
- Objective: the visitor badges (ticket 658976) had the school logo drawn over the name and date.
- Cause: the author kept text clear of the logo by typing spaces before each line; Slides draws spaces narrower than the original face, so the text landed under the logo. The logo can also sit behind the table in drawing order.
- Files changed: `publisher_slides.py` -- `_clear_of_pictures` (called from `_table_layout`): for a table cell with a picture over its left side (at any depth, `in_front_of(any_depth=True)`), a paragraph that starts with 3 or more spaces loses its padding spaces and gets a start indent that clears the picture by 8 pt (`_unpadded`). Unpadded text is untouched. `test_publisher_table_pictures.py` (4 tests).
- Checked live (working-tree code on the homelab, the owner's Drive): all ten badges now read clear of the logo.
- Checks: 977 platform tests pass; Ruff, format, mypy clean.
- Unresolved: not deployed; the Trophy Certificates file (2.4 MB) needed the parser time limit raised to 300 s on the homelab (336 s in all) and would fail on the hosted service ("took too long to analyse"); its output was too large to export, so it has not been looked at.
- Next task: none claimed.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/DOCX)
- Date: 2026-11-23
- Branch: `rtf-and-boxed-equations`, based on main `d437d55`.
- Objective: the two ticket sample files -- an `.rtf` worksheet and a maths `.docx` that Google refused (HTTP 500 on upload).
- Files changed: `rtf.py` (new; checks the file is RTF, then hands it to Google's own import through `doc.import_document`, which `doc.py` now shares; report `rtf_not_repaired`), `package.py` (RTF format), `pipelines.py`, `worker.py`, `index.html`. `docs.py` -- `unwrap_equation_boxes`, run first in `transform`: Google Docs writes every equation inside `<m:box>`, and Google's importer returns HTTP 500 for a file holding one (found by bisecting the ticket file: one boxed equation fails, the same equation unboxed imports). Boxes, nested ones included, are replaced by their contents. Tests: `test_rtf_support.py` (9), one in `test_docx_equations.py`.
- Checked live (working-tree code on the homelab, the owner's Drive): the `.rtf` imports cleanly (coins, Venn diagram, fractions, page numbers all kept); the maths `.docx` now converts and its equations, brackets and powers render correctly. The sign-in token was revoked and shredded afterwards.
- Checks: 973 platform tests pass; Ruff, format, mypy clean.
- Unresolved: not deployed; the RTF output has no layout repair (same as `.doc`); the Drive test folders hold bisect files (`v_`, `w_`, `x_`, `y_`, `z_`, `q_` prefixes) in "RTF and DOCX ticket test - reports".
- Next task: none claimed.
