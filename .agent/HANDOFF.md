# Handoff

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

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform)
- Date: 2026-11-23
- Branch: `doc-support`, based on main `243bdf4`.
- Objective: accept legacy `.doc` files and password-protected Office files (ticket 660358 and others).
- Files changed: new `doc.py` (checks a `.doc` is a Word document; converts by uploading it for Google's own import; reports `doc_not_repaired`) and `protected.py` (unlocks a protected `.doc`/`.docx`/`.pptx`/`.xlsx`/`.xlsm` with msoffcrypto-tool, in the worker). `package.py` (DOC format), `pipelines.py`, `worker.py` (password read from stdin, unlock before analysing), `jobs.preflight(password=)`, `web.py` (`X-File-Password` header, up to 256 characters), `static/app.js` + `index.html` + `style.css` (a password field appears on a protected file's row, then Convert again). `pyproject.toml` and both locks: `msoffcrypto-tool==6.1.0`, `olefile==0.47`. Tests: `test_doc_support.py` (16, including through the app with the real worker) and two synthetic Word fixtures in `tests/platform/data` (personal information removed; the password is in the test).
- Checks: 960 platform tests pass; Ruff, format, mypy clean. `check_secrets` could not run locally (no detect-secrets); the test password carries the allowlist pragma.
- Unresolved: not yet run through live Google; only RC4-protected `.doc` tested (Word's default); the four protected `.doc` files from the ticket have an unknown password, so they were not run; a protected file in a Drive-picked batch is retried by choosing it again.
- Next task: none claimed.
