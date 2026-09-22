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

#12 has now been built and tested on Linux CI, and all five checks are green.
The container build passes and runs the 92 C++ unit tests on a clean Ubuntu
base during the image build. Two CI failures were found and fixed on the way,
both in platform-owned files that the Publisher session could not have reached:
`.dockerignore` excluded `**` and re-included only the platform image's files,
so any second image built from the repository root failed; and the secret scan
flagged PUB-001's SHA-256 as high-entropy hex, now excluded by that exact key
alone.

PUB-001 acceptance is **no longer blocked**. The private fixture was supplied,
and the parser reproduced every expected count with zero diagnostics: 4 pages at
420.944882 x 595.275591 pt, 22 elements, 82 paragraphs, 147 styled runs, 204
text insertions, 12 image placements over 11 deduplicated assets, one 1x3 table,
two paths, one rendering layer and three fonts. It runs locally only -- the
document is a real school booklet and must never be committed -- so the CI job
reports NOT RUN ON CI rather than claiming a pass. 92 C++ tests and 55 Python
tests pass with the fixture supplied; 22 skip without it.

What remains unverified for Publisher is breadth, not depth: only one real
document has been parsed. PUB-001 contains no authored group, no
`drawGraphicObject`, no master page, no metafile image, no embedded font, no
list, no link and no rotated object. Those paths have synthetic callback tests
only. PUB-002 onwards are the next real dependency, and #12 stays draft until
then.

Live OAuth, real Google conversion and visual fidelity remain unverified for
both PPTX and DOCX. Every Google interaction is covered by test doubles only.
No GCP resources are deployed.

The next milestone is a Google Cloud project. Note that verification does not
require Cloud Run: `config.py` permits `http://localhost`, so the app can be run
locally against a real OAuth client. Cloud Run, billing and a public hostname
are only needed to put it in front of staff.
