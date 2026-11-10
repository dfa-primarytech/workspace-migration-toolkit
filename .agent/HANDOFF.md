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
- Branch: `docx-flowchart-boxes`, based on main `b15b382`.
- Objective: a one-page Word flowchart (13 text boxes and arrows, anchored to paragraphs) converted to three pages with its boxes in the wrong order.
- Files changed: `docs.py` -- `_in_page_order` puts boxes anchored in one paragraph top to bottom, then left to right (they were in the order drawn); `_side_by_side`/`_replace_pair` keep two boxes that share a band of the page beside each other, as two cells of a borderless table, instead of stacking them. `test_docx_page_textbox.py` (5 new), `test_docx_sections.py` (one test's boxes moved apart so they do not pair).
- Checks: platform tests pass; Ruff, format, mypy clean.
- Unresolved: not yet confirmed in Google; the flow arrows are still floating shapes that Docs keeps unchanged (they no longer sit by their boxes); Word cannot open the converted file (empty drawing shells), so Word is no proxy here.
- Next task: none claimed.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/PPTX)
- Date: 2026-10-21
- Branch: `hosted-animation-video`, based on main `1fce024`.
- Objective: the hosted conversion records heavy animations and wraps sounds itself, so staff no longer need to run anything.
- Files changed:
  - `animation_video.py`: `hosted_enabled()` (on unless `WMT_HOSTED_ANIMATION=off`, and only where ffmpeg exists) and `record_hosted()` (the heaviest 3 slides, each at most 120 s of video, 240 s in all; slides beyond 3 are named in a warning; never raises).
  - `google.convert`: after the embedded videos, records animations (`report["animationVideos"]`) and wraps sounds (`report["soundVideos"]`, skipping slides given a video). Each step is non-fatal.
  - `pyproject.toml`, both lock files: `imageio-ffmpeg==0.6.0`, whose wheel carries a static ffmpeg (about 60 MB on the image).
  - Tests: `test_hosted_animation.py` (3), five more in `test_animation_video.py`; `conftest.py` switches recording off for every other test.
- Checks: 926 platform tests pass; Ruff, format, mypy clean.
- Unresolved: not yet run against live Google through the deployed service; the Docker build with ffmpeg not yet checked; the wrapped-sound and animation videos are private to their owner (viewers need access); the cost of recording lands on Cloud Run (about 45 s of 2 vCPU for a 77 s slide), kept bounded by the caps above. `WMT_HOSTED_ANIMATION=off` is the switch if the bill needs it.
- Next task: none claimed.

---
