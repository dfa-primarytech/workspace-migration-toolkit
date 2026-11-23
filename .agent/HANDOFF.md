# Handoff

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
