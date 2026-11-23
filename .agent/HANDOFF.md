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

---
