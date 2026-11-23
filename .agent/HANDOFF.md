# Handoff

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

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/Publisher)
- Date: 2026-11-23
- Branch: `publisher-bulk-fixes`, based on main `82ee663`.
- Objective: four faults found checking a 23-file Publisher bulk run (ticket 658694): numbered lists showing 1. on every item, text under pictures, WordArt titles wrapping over boxes, a heading cut off at the page top, tick boxes drifting off their lines.
- Files changed: `publisher_slides.py` -- empty list paragraphs between items of one list are folded into space below the item (`_folded`), so numbering continues; a text frame starting above the page is moved to its top edge (`_onto_page`, note `text-above-page`); WordArt is sized to its width too, with an estimate for faces that cannot be measured; `text_requests` takes `above`. `publisher_wrap.py` -- pictures are cleared with a 14 pt vertical tolerance and an 8 pt gap, a picture in the middle of a line takes text on the side with more room (limit 75 percent of the line), and a line beside a small box is moved down to it (`_aligned`, at most 40 pt, only if the text still fits at the same size). Tests added in the lists, wrap, slides and wordart files.
- Checked live (through the app's own code on the homelab, four files re-converted): numbering 1 to 6, the date visible, titles on one line clear of their boxes, the Rating picture no longer overprints its line, the tick boxes nearer their lines.
- Checks: 944 platform tests pass; Ruff, format, mypy clean.
- Unresolved: a line beside a picture can still touch it (INDUSTRIES B TEXT, item 6), probably because the fonts Slides draws unknown families in differ from the Arial assumed (the exported PDF showed a serif face); the tick boxes are closer but not exact; a line just below the Rating picture now also wraps narrower than needed. No originals could be rendered (no Publisher), so fidelity was judged from the parsed layout.
- Next task: `.doc` support, once the ticket sample files arrive.
