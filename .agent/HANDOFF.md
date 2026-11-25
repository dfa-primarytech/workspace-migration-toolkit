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

- Agent: Claude Code (Claude Sonnet 5.5, platform/UI)
- Date: 2026-11-24
- Branch: `whats-new-page`, based on main `a32de2a`.
- Objective: a page on the converter where staff can see what has been fixed or added, to check whether their problem is gone.
- Files changed: new `patch_notes.py` (the entries, newest first, in plain words; `render()` builds the page with everything escaped), `web.py` (public `/whats-new` route), `static/index.html` (footer link), `static/style.css` (kind badges), `AGENTS.md` (rule: a change staff can see adds an entry in the same PR). `test_patch_notes.py` (5 tests: public, linked, newest-first and valid kinds, no client or ticket names, escaping).
- Checks: 982 platform tests pass; Ruff, format, mypy clean. Not yet looked at in a browser.
- Unresolved: not deployed. The reports folder `Newbald 658976 converted - reports` could not be trashed with the Drive connector (no permission); the owner removes it in Drive.
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
