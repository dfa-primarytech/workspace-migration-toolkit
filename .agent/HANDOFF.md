# Handoff

- Agent: Claude Code
- Date: 2026-09-22
- Branch: `feat/docx-parser-renderer`, branched from `feat/platform-pptx-preflight` (PR #8). Must land after it.
- Objective: port the DOCX conversion knowledge from the Apps Script fixer onto the platform, as a source parser and a Google Docs renderer per PROJECT.md section 4.
- Files changed: `app/workspace_toolkit/docx.py` (new parser), `app/workspace_toolkit/docs.py` (new renderer), `app/workspace_toolkit/package.py` (parameterised by format), `tests/platform/test_docx.py` (new), coordination files.
- Completed: anchor classification (text box, picture, ink, unsupported) with an explicit registry for groups, canvases, charts, chartex and SmartArt; intermediate model with bounds in points, per-section pages, fonts, compatibility and warnings; transform passes (mc:Fallback stripping, ink removal, background removal, anchor rewriting, conservative empty-paragraph removal); floating-table positioning from real anchor coordinates; backing pictures kept and pushed behind the text; package rewriting that preserves every other part byte-for-byte.
- Checks: 58 Python tests pass (39 existing + 19 new). Ruff check and format clean. Verified Codex's PPTX path is unaffected by the package.py change.
- Known failures: none in local checks.
- Unresolved: the renderer is not wired into `web.py`, `jobs.py` or `google.py` — there is no DOCX endpoint or Drive import path yet, so nothing converts end to end. No real DOCX has been through the platform. Legacy VML-only pictures (`v:imagedata` with no DrawingML sibling) are parsed but not yet rewritten; the Apps Script `_fixLegacyPicts` pass has not been ported. Header and footer parts still get no structural passes. Google's z-ordering of a floating table over a behind-text picture is reasoned from Docs' own "Behind text" support, not observed.
- Decisions: see DECISIONS.md — DOCX supersedes "preserve src/"; rendering rewrites the package rather than calling the Docs API; Google honours w:tblpPr (verified); stdlib ElementTree over lxml; Package parameterised by format.
- Next task: wire DOCX into the web/job/Drive path so a file converts end to end, then run a real worksheet through it and compare against the Apps Script output, which is the current behavioural baseline.
- Warnings: do not prune `feat/docx-floating-tables` — it is the reference implementation for this port. Schema order is load-bearing in two places: CT_TblPrBase requires tblpPr and tblOverlap before tblW, and CT_Anchor requires any wrap element before wp:docPr. Getting either wrong makes Word reject the file. Do not add real school documents to Git.
