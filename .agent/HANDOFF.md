# Handoff

- Agent: Claude Code / QuietHeron, working the issue queue at the human's request
- Date: 2026-09-23
- Branches: `fix/xml-element-limit` (#59, fixes #46), `fix/dangling-relationships` (#61, fixes #47, stacked on #59), `fix/pptx-font-rewrite-scope` (this branch, fixes #50). All based on main `6ae8dee`.
- Objective: the platform issues from the audit that don't touch the DOCX renderer, where SilverDog has #57 open.
- Completed: #46: XML elements counted during parsing, limit a setting (500,000), message names the limit. #47: a relationship to an absent part is reported, not fatal (a missing slide still is); resolution is case-insensitive. #50: the PPTX font rewrite touches only `<a:latin>` start tags, skips the symbol charset, and drops the stale PANOSE, pitch and charset. Closed the legacy Apps Script issues #1–#4 as not planned, at the human's request.
- Checks: each branch passes the platform suite locally (259 / 262 / 261 passed, 8 skipped); ruff, format, mypy and bandit clean.
- Known failures: none.
- Unresolved: PPTX still applies MEDIUM-confidence candidates automatically where DOCX applies HIGH only. That's the shared font service owner's decision (#27, `docs/publisher-font-audit.md`) and is not changed here.
- Decisions: none new.
- Next task: merge #59 before #61. DOCX issues #44, #48 and #49 are left for SilverDog. #36, #51, #52, #53, #54 and #55 remain.
- Warnings: agent-mail is still unavailable to this session (no registration token), so issues were claimed by GitHub comment instead.

---

## Previous handoff

- Agent: Claude Code / QuietHeron, standing in on DOCX at the human's request
- Date: 2026-09-23
- Branch: `fix/docx-blank-lines-and-text-check`, based on main `5510749`
- Objective: fix #42 (the empty-paragraph pass deleted every blank line, page-break paragraph and empty header) and #43 (the post-import text check reported missing text on most real documents).
- Files changed: `app/workspace_toolkit/docs.py` (`transform`, `remove_empty_paragraphs`, `source_text`), `tests/platform/test_docx_blank_lines.py` (new, 11 tests), coordination files.
- Completed: `transform` records which paragraphs were already empty before any pass, and `remove_empty_paragraphs` removes only paragraphs a pass emptied (for example by removing ink), never the last paragraph of a cell, header, footer or text box. `source_text` joins runs within a paragraph with nothing, separates paragraphs, tabs and breaks, skips `mc:Fallback` and `w:vanish` runs, and still treats a skipped field result as a word boundary.
- Checks: 241 platform tests pass, 8 skip (LibreOffice validity tests, as before); ruff, format, mypy and bandit clean.
- Known failures: none.
- Unresolved: hidden text applied through a character style is not resolved. Nothing here was run against live Google. The blank-page behaviour of kept separator paragraphs after import is #54's subject, not fixed here.
- Decisions: none new. The emptiness rule itself is unchanged; only which paragraphs it may act on.
- Next task: DOCX review by someone other than the author (CURRENT.md notes DOCX has no independent reviewer), then #44/#45.
- Warnings: agent-mail file reservation was not taken, because this session lost its agent-mail registration token.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-23
- Branch: `test/publisher-breadth`, based on main `135f744`
- Objective: parser breadth for the constructs PUB-001 lacks, built on what libmspub 0.1.4 actually emits rather than on assumed callbacks.
- Files changed: `native/pub-parser/src/collector.{h,cpp}`, `src/model.h`, `tests/test_libmspub_shapes.cpp` (new), `tests/test_collector.cpp` and `tests/test_text.cpp` (labels only), `CMakeLists.txt`, `packages/document-model/schema.json` (one description), `docs/publisher-parser.md`, coordination files.
- Completed: read libmspub-0.1.4's source and found it never calls `openGroup`, `startMasterPage`, the list callbacks, `openLink` or `insertField`; emits groups as layers; folds rotation and flips of everything but text into outlines; paints master content into every page; and calls `drawGraphicObject` only for BorderArt. The parser now classifies each layer at close (probable authored group, multi-pass wrapper, or clip wrapper), recovers rotation from rotated rectangular outlines instead of reading rotated pictures as masks, flags mirrored outlines, rotated fills and border-art tiles, and treats a bitmap-filled `drawRectangle` as rectangular (it was classed as a mask). 13 new tests; the unreachable ones are labelled.
- Checks: 105/105 C++ tests pass in CI (native job and container build); Python lint green. Not compiled locally: this machine has no C++ toolchain.
- Known failures: none in CI.
- Unresolved: **PUB-001 acceptance must be re-run locally.** Its test asserts its one layer is a wrapper; under the new rule it most likely still is, but that is unverified. If it reclassifies, record it, do not edit `expected.json` to match. Nothing here is verified against a real grouped, rotated, flipped, cropped or border-art `.pub`.
- Decisions: "a layer is never a group" superseded. See DECISIONS.md, 2026-09-23.
- Next task: the renderer-readiness gap report (now largely this table: groups inferred, master content duplicated per page, crops unapplied, border art as many images, lists/links unrecoverable), then the font audit. Stop before any Slides renderer code (PROJECT.md section 38).
- Warnings: the grouping rule is a heuristic from library source. Conservative by design: a false negative loses grouping, never content.

---

## Previous handoff

- Agent: Codex / SilentMountain
- Date: 2026-09-23
- Branch: `feat/shared-font-substitution`, based on main `68f9eab`
- Objective: create one reported font-substitution policy for PPTX, DOCX and PUB,
  with an education-focused mapping and PPTX application path.
- Changed files: shared fonts module; PPTX worker and Google upload path; platform
  tests; `docs/font-compatibility.md`; coordination files.
- Work completed: central AVAILABLE/SUBSTITUTED/UNKNOWN catalogue; exact Office
  metric alternatives; education/handwriting candidates; cautious accessibility
  recommendations; PPTX run and theme analysis; credential-free package rewrite;
  converted-package upload; structured occurrence reporting.
- Checks: 155 platform tests passed, 6 skipped; Ruff and formatting clean; mypy
  clean; 19 legacy Node regressions passed. A focused Google test proves the
  rewritten PPTX, rather than the source, is uploaded.
- Known failures: none in offline checks.
- Unresolved: Google Workspace font availability and visual fidelity need live
  validation; DOCX and Publisher integrations are assigned but not in this branch.
- Decisions: see 2026-09-23 font decision in `DECISIONS.md`.
- Next task: review and merge this branch, then let DOCX and Publisher consume
  the shared API and validate representative education resources.
- Warnings: Google Fonts catalogue membership is not a live Workspace guarantee.
  Do not auto-apply mappings marked `manualReview`; do not add font binaries.

---

- Agent: Claude Code
- Date: 2026-09-22
- Branch: `feat/docx-parser-renderer`, branched from `feat/platform-pptx-preflight` (PR #8). Must land after it.
- Objective: port the DOCX conversion knowledge onto the platform as a parser and Docs renderer per PROJECT.md section 4, then wire it through the web, job and Drive paths so a .docx converts end to end.
- Files changed: `app/workspace_toolkit/docx.py` and `docs.py` (new), `pipelines.py` (new registry), `package.py` (parameterised by format), `jobs.py`, `worker.py`, `web.py`, `google.py`, `static/app.js`, `static/index.html`, `tests/platform/test_docx.py` (new), README, docs/research.md, coordination files.
- Completed: legacy VML-only pictures rebuilt as inline DrawingML; headers and footers given the same structural passes as the body; anchor classification (text box, picture, ink, unsupported) with an explicit registry for groups, canvases, charts, chartex and SmartArt; intermediate model with bounds in points, per-section pages, fonts, compatibility and warnings; transform passes (mc:Fallback stripping, ink removal, background removal, anchor rewriting, conservative empty-paragraph removal); floating-table positioning from real anchor coordinates; backing pictures kept and pushed behind the text; package rewriting that preserves every other part byte-for-byte.
- Checks: 78 Python tests pass (39 existing + 39 new). Ruff check/format, mypy and Bandit clean; app.js syntax checked. Codex's PPTX path verified unaffected. Smoke-tested offline against four real Word worksheets: parser and renderer agree exactly on every one, producing 6/10/4/10 positioned tables with coordinates matching the source anchors. One document's 4 legacy VML-only pictures convert and no <w:pict> remains; its header and footer are now processed as story parts.
- Known failures: none in local checks.
- Unresolved: no real DOCX has been through a live Google conversion — every Google interaction is covered by a test double only. Backing-picture/behind-text handling is not exercised by any real sample (see DECISIONS). Google's z-ordering of a floating table over a behind-text picture is reasoned from Docs' own "Behind text" support, not observed.
- Decisions: see DECISIONS.md — DOCX supersedes "preserve src/"; rendering rewrites the package rather than calling the Docs API; Google honours w:tblpPr (verified); stdlib ElementTree over lxml; Package parameterised by format.
- Next task: wire DOCX into the web/job/Drive path so a file converts end to end, then run a real worksheet through it and compare against the Apps Script output, which is the current behavioural baseline.
- Warnings: do not prune `feat/docx-floating-tables` — it is the reference implementation for this port. Schema order is load-bearing in two places: CT_TblPrBase requires tblpPr and tblOverlap before tblW, and CT_Anchor requires any wrap element before wp:docPr. Getting either wrong makes Word reject the file. Do not add real school documents to Git.

---

## Previous handoff (Codex, platform and PPTX)

- Agent: Codex
- Date: 2026-09-22
- Branch: `feat/platform-pptx-preflight`
- Base: `origin/main` at `a145127`
- Objective: add the shared application foundation and first PPTX preflight/native-import workflow while preserving the Apps Script DOCX fixer.
- Files changed: coordination files; Python application under `app/`; platform tests; Docker/Cloud Run/CI configuration; dependency locks; `PROJECT.md`; `docs/platform.md`; `.gitignore`.
- Completed: bounded PPTX package inspection; text/font/asset/relationship/risk manifest; private extraction of embedded assets; Google OAuth state+PKCE flow; `drive.file` native import; private recovered-asset uploads; Slides count/size/text and image/table/chart count read-back checks; reports; temporary job cleanup; offline CLI; container and CI definitions.
- Checks: 48 Python tests and all 19 DOCX Node regression tests passed. Ruff, formatting, mypy, Bandit, pip-audit, secret scan and JavaScript syntax passed locally. GitHub CI previously passed its Linux container build/smoke test and will rerun for this update. Offline preflight passed against files generated by installed Microsoft PowerPoint: a two-slide 720 x 540 pt deck with 2 text boxes, 1 shape and 1 table; and a one-slide media deck with an image, WAV audio and editable caption. The media package yielded two PNG assets (the image and PowerPoint's audio preview) plus one WAV asset, with the audio timing reported as intentionally ignored. Validation artifacts remain outside Git.
- Known failures: none in local checks.
- Unresolved: no live OAuth/Google conversion; no real PPTX regression fixture; no visual fidelity check; no automatic repair/media reinsertion; no durable queue/idempotency for interrupted Google writes.
- Decisions: FastAPI stays separate from Apps Script; native Drive import renders PPTX; preflight provides evidence and warnings; user OAuth uses `drive.file`; documents and tokens are not stored centrally. See `DECISIONS.md`.
- Next task: continue deterministic parser and API-boundary fixtures. Create GCP test configuration only after the local codebase is ready.
- Warnings: do not edit this branch/worktree concurrently. Do not add credentials or real school documents to Git. A candidate `NATIVE` status is not verified compatibility. Google writes can leave private partial outputs after uncertain failures.
