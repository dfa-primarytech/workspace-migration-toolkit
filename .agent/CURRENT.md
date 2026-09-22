# Current state

Main is at `a145127`: the Apps Script DOCX fixer with 19 Node regression tests.
It is now legacy. The project has moved to the Cloud Run platform for all M365
formats, so no further Apps Script work is planned and PR #10 was closed
unmerged (its branch is kept as the DOCX reference implementation).

The shared FastAPI platform and PPTX preflight are on
`feat/platform-pptx-preflight` (PR #8, open). The DOCX parser and Google Docs
renderer are on `feat/docx-parser-renderer`, branched from it, and must land
after it.

58 Python tests pass across both: Codex's 39 plus 19 for DOCX. Ruff, formatting
and the full suite are clean. Live OAuth, real Google conversion of a DOCX
through the platform, and visual fidelity remain unverified. Publisher is still
deferred — but Microsoft Publisher reaches end of support on 1 October 2026,
after which .pub files cannot be opened in Publisher at all. Nine days from this
entry. No GCP resources are deployed.
