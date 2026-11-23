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
- Branch: `docx-flow-inline`, based on main `f6cb3c8`.
- Objective: the flowchart, reconverted on revision 00014, had the right order, side-by-side pairs and blue arrows, but the first box (a floating table) sat below its arrow and the last row spilled to a second page.
- Files changed: `docs.py` -- a box drawn in a paragraph with other boxes or flow arrows is built in the text (not floating) at the text width, so the arrow lines and pairs keep their place. A lone box still floats. Two tests added.
- Checks: 934 platform tests pass; Ruff, format, mypy clean.
- Unresolved: not yet confirmed in Google; the page count may still be 2 (box heights and the blank lines between rows).
- Next task: `.doc` support (see the owner's plan), starting with Google's native import for `.doc` and a password step; the owner's ticket sample files were not yet received.

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
