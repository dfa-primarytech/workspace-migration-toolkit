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
