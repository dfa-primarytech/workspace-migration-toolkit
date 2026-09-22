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
because the Publisher session gets 403 on push. **It still has no write access.**
Until it is added as a collaborator, or switches to forking, every session there
ends needing a manual rescue. Nothing in #12 has been compiled or tested here;
its Docker and CI files are planned but not yet in the branch, so no Linux CI
has run. PUB-001 regression acceptance remains blocked on the private fixture.

Live OAuth, real Google conversion and visual fidelity remain unverified for
both PPTX and DOCX. Every Google interaction is covered by test doubles only.
No GCP resources are deployed.

The next milestone is a Google Cloud project. Note that verification does not
require Cloud Run: `config.py` permits `http://localhost`, so the app can be run
locally against a real OAuth client. Cloud Run, billing and a public hostname
are only needed to put it in front of staff.
