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
- Date: 2026-11-10
- Branch: `docx-flow-arrows`, based on main `624d1b5`.
- Objective: after the flowchart fix (#201, live as revision 00013: right order, boxes side by side), the converted file was still 2 pages and its six flow arrows floated over the text of the boxes.
- Files changed: `docs.py` -- `_flow_arrows`/`_mark_flow`: arrow and connector shapes anchored in a paragraph with text boxes are removed and shown as a small blue arrow in the blank line between one box (or pair) and the next; counted as `arrows` in the conversion report. The arrows between the two boxes of a pair are not kept. Tests added; one exact-report test gains `arrows: 0`.
- Checks: platform tests pass; Ruff, format, mypy clean.
- Unresolved: not yet confirmed in Google; the page count may still be 2 (box heights and spacing); a diagonal connector becomes a plain down arrow.
- Next task: none claimed.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/DOCX)
- Date: 2026-11-10
- Branch: `docx-flowchart-boxes`, based on main `b15b382`.
- Objective: a one-page Word flowchart (13 text boxes and arrows, anchored to paragraphs) converted to three pages with its boxes in the wrong order.
- Files changed: `docs.py` -- `_in_page_order` puts boxes anchored in one paragraph top to bottom, then left to right (they were in the order drawn); `_side_by_side`/`_replace_pair` keep two boxes that share a band of the page beside each other, as two cells of a borderless table, instead of stacking them. `test_docx_page_textbox.py` (5 new), `test_docx_sections.py` (one test's boxes moved apart so they do not pair).
- Checks: platform tests pass; Ruff, format, mypy clean.
- Unresolved: not yet confirmed in Google; the flow arrows are still floating shapes that Docs keeps unchanged (they no longer sit by their boxes); Word cannot open the converted file (empty drawing shells), so Word is no proxy here.
- Next task: none claimed.

---
