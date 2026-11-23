# Handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/native)
- Date: 2026-11-10
- Branch: `claude/nostalgic-franklin-d08ebf`, based on main `c50039d`. PR #203.
- Objective: fix CI job "Native adapter (Linux)" (publisher.yml), which failed building libmspub with `'int64_t' was not declared` in Coordinate.h.
- Cause: libmspub 0.1.4 uses `int64_t` in several files without `<cstdint>`; GCC 14+ on GitHub's current ubuntu runner no longer includes it transitively. The Dockerfile build uses python:3.12-slim (older GCC), so it was unaffected. Patch 0000 only covered MSPUBMetaData.h.
- Fix: `native/pub-parser/libmspub/build.sh` passes `CXXFLAGS="-O2 -g0 -include cstdint"`, covering every file; the patch set is unchanged.
- Checked: publisher-parser workflow_dispatch run 42804750137 on this branch: all four jobs green, including Native adapter (Linux) and Container build.
- Unresolved: none. The Dockerfile uses the same build.sh, so it is covered when its Debian base moves to a newer GCC.
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

---
