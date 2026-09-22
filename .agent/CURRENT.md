# Current state

## Who owns what

Three agents work in parallel. Each owns its own branch and file areas, and
communicates through its draft PR. Do not edit another agent's files.

| Agent | Branch | Owns |
|---|---|---|
| Personal Codex | merged as #8 | Shared platform, PPTX → Slides |
| Work Claude | merged as #11 | DOCX → Docs: parser, renderer, pipeline wiring |
| Second Claude | `feat/publisher-ir`, draft PR #12 | Publisher → intermediate representation |

Note on `app/`: it is no longer solely the platform's. `docx.py`, `docs.py` and
`pipelines.py` (plus `tests/platform/test_docx.py`) are the DOCX stream's; the
rest is the platform's. An earlier instruction attributing all of `app/` to the
PPTX branch predates the DOCX port.

## Where things stand

`main` carries the shared FastAPI platform, the PPTX preflight and native
import, the specification and these coordination files, after #8 merged.

`main` now also carries the DOCX parser, Google Docs renderer and the
web/job/Drive wiring. A `.docx` converts by the same route as a `.pptx`, chosen
by a pipeline registry; headers and footers get the same structural passes as
the body. 87 Python tests pass: 48 platform, 39 DOCX. Ruff, formatting, mypy,
Bandit and the secret scan are clean, and CI is green on main.

The Apps Script fixer under `src/` is legacy and frozen. No further work is
planned on it; its 19 Node regression tests still pass and it remains deployed
for staff use. PR #10 (floating tables) was closed unmerged, and its branch
`feat/docx-floating-tables` is kept as the DOCX reference implementation --
do not prune it.

Publisher is active, not deferred, and owned by the second Claude. Its first
milestone -- the native libmspub callback adapter and intermediate model -- is
on `feat/publisher-ir` as draft PR #12: roughly 5,700 lines of C++ and tests.

That work was recovered by git bundle and pushed from another environment,
because the Publisher session gets 403 on push. **This is a token problem, not a
permissions problem** -- that session signs in as Scrappy995, which already holds
write, and Codex pushes fine as the same account. See BACKLOG item 2.

PUB-001 has since been supplied and parsed: 4 pages, 82 paragraphs, 147 runs, 12
image placements over 11 assets, zero diagnostics, every predicted count
reproduced. CI now runs on that branch and all five checks pass, including the
container build -- so the "container never built" and "CI never ran" gaps are
closed. Still open: only one real document has been parsed, and PUB-001 cannot
run on a public runner because it must never be committed.

Live OAuth, real Google conversion and visual fidelity remain unverified for
both PPTX and DOCX. Every Google interaction is covered by test doubles only.
No GCP resources are deployed.

The next milestone is a Google Cloud project. Note that verification does not
require Cloud Run: `config.py` permits `http://localhost`, so the app can be run
locally against a real OAuth client. Cloud Run, billing and a public hostname
are only needed to put it in front of staff.
