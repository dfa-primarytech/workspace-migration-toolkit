# Current state

## Coordination

SilentMountain coordinated until 23 September 2026 and has run out of budget.
The human moved coordination to SilverDog, which also owns the DOCX stream.

**This means DOCX no longer has an independent reviewer, and that is a real
loss rather than a formality.** SilentMountain caught three defects in DOCX
work that had passed its author's own checks: equations counted in only one
part, an explicitly left-to-right text box overridden by its anchor, and a
user-facing string asserting behaviour Google has never been observed to have.
Publisher and the platform still get an independent reviewer. DOCX does not.
Anyone picking this up with budget to spare should review DOCX pull requests.

Unchanged: no merging without the human's approval; nothing claims live Google
behaviour; no GCP, keys or billable resources; real documents are never
committed.

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

Personal Codex is developing `feat/shared-font-substitution` from main at
`68f9eab`. It adds the shared font catalogue and makes PPTX render a converted
package with reviewed mappings before native import. DOCX and Publisher owners
have been assigned input audits and later integration against the same API.
Unknown and accessibility-sensitive fonts are retained for review.

DOCX section boundaries, RTL preservation and equation diagnostics are merged
as #18, #19 and #21. SilverDog has been assigned TOC preservation next.

`main` carries the shared FastAPI platform, the PPTX preflight and native
import, the specification and these coordination files, after #8 merged.

`main` now also carries the DOCX parser, Google Docs renderer and the
web/job/Drive wiring. A `.docx` converts by the same route as a `.pptx`, chosen
by a pipeline registry; headers and footers get the same structural passes as
the body.

Four further DOCX milestones merged (#18 `2d5e0f3`, #19 `e7ec4d3`, #21
`68f9eab`):

* **Multi-section documents.** A text box anchored to a section-break paragraph
  had its converted table placed in the *next* section, so portrait content
  could render landscape. Nothing errored and no count changed. Fixed, and the
  fixtures now cover the body-level `sectPr` shape that every real worksheet
  uses and no fixture previously had.
* **Right-to-left.** Direction already survived, because the converter
  relocates markup rather than rebuilding it; that is now pinned. What was
  missing was direction on the parts the converter *creates* -- the table, an
  empty cell's filler paragraph, table separators.
* **Equations.** They survive intact. The finding was that `verify()` compared
  `<w:t>` tokens only, so a lost equation was invisible to it. Counted and
  reported as unverified instead.

Two further milestones merged: computed-field handling (#22 `9d2c51e`) and
the shared font service (#23 `af5ff6c`, coordinator's).

* **Contents pages.** A TOC's cached page numbers are ordinary `<w:t>`, so
  they counted as body text. Any difference in pagination then read as lost
  content -- a correct but renumbered contents page reported missing text once
  per entry. Computed field results are now excluded from the comparison and
  reported as a count instead; authored results such as a HYPERLINK's display
  text still count.
* **Fonts.** `fonts()` read literal `w:rFonts` only, so a document using
  Word's default theme fonts reported *no fonts at all*, as did one whose
  fonts lived in its styles. `font_requirements()` now resolves themes and
  style inheritance, keeps the script dimension, attaches `fontTable.xml`
  matching metadata, and marks symbol fonts as a class that must not be
  substituted.

217 Python tests pass, 41 skip (LibreOffice and Publisher fixtures). Ruff,
formatting, mypy, Bandit and the secret scan are clean, and CI is green on
main.

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
