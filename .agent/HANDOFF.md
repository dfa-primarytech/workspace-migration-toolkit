# Handoff

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
