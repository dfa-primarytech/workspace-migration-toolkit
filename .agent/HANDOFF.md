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
