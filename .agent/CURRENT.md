# Current state

## Who owns what

Three agents work in parallel. Each owns its own branch and file areas, and
communicates through its draft PR. Do not edit another agent's files.

| Agent | Branch | Owns |
|---|---|---|
| Personal Codex | `feat/platform-pptx-preflight` (merged as #8) | Shared platform, PPTX → Slides |
| Work Claude | `feat/docx-parser-renderer` (PR #11) | DOCX → Docs: parser, renderer, pipeline wiring |
| Second Claude | `feat/publisher-ir` | Publisher → intermediate representation |

Note on `app/`: it is no longer solely the platform's. `docx.py`, `docs.py` and
`pipelines.py` (plus `tests/platform/test_docx.py`) are the DOCX stream's; the
rest is the platform's. An earlier instruction attributing all of `app/` to the
PPTX branch predates the DOCX port.

## Where things stand

`main` carries the shared FastAPI platform, the PPTX preflight and native
import, the specification and these coordination files, after #8 merged.

The DOCX parser, Google Docs renderer and the web/job/Drive wiring are on
`feat/docx-parser-renderer` (PR #11), rebased onto the merged main. A `.docx`
converts by the same route as a `.pptx`, chosen by a pipeline registry; headers
and footers get the same structural passes as the body. 87 Python tests pass:
48 platform, 39 DOCX. Ruff, formatting, mypy and Bandit are clean.

The Apps Script fixer under `src/` is legacy and frozen. No further work is
planned on it; its 19 Node regression tests still pass and it remains deployed
for staff use. PR #10 (floating tables) was closed unmerged, and its branch
`feat/docx-floating-tables` is kept as the DOCX reference implementation --
do not prune it.

Publisher is active, not deferred, and owned by the second Claude. Its branch
had not reached the remote at the time of writing: that session reported 403 on
push, so its work existed only in one environment. Confirm it has been pushed
before relying on it.

Live OAuth, real Google conversion and visual fidelity remain unverified for
both PPTX and DOCX. Every Google interaction is covered by test doubles only.
No GCP resources are deployed.
