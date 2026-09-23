# Current state

## First run against live Google, 23 September 2026

The toolkit ran end to end against a real Google account for the first time:
a real Word worksheet was converted to a Google Doc through the app's own
`/api/convert`, not by hand. Three things came out of it.

**The font fix holds.** Every family resolved `AVAILABLE` with no replacement,
against 1,476 substitutions the same worksheet drew before #30.

**Three upload defects, now fixed.** 27 of 65 private asset copies uploaded and
the 28th was refused; that one refusal abandoned the other 37, skipped the
document's own verification, and reported a good conversion as failed. The
failing status was also discarded before it reached the report, so the cause
could not be read off it afterwards. Retries, per-asset tolerance and a
preserved failure detail are in `fix/asset-upload-resilience`.

**Every run made a new top-level folder.** There is now one `Workspace
conversions` library with a dated subfolder per job. Found by the human.

Still unmeasured: whether the offsets of in-cell floating images survive, and
whether Google de-duplicates images stacked at identical offsets. The latter
is the standing explanation for 12 lost image placements and is not yet tested.

**Only what the import drops is copied, and it is named.** Every picture in
a document was being copied out beside it: 65 photographs became 65 uploads,
65 files to scroll past and 65 chances to be throttled, for pictures the
importer had already carried in safely. Only embedded audio, video, OLE
objects and picture formats no browser draws are copied now -- which was the
original point of the copies. Corrected by the human.

The copies that remain are named. Every private copy went to Drive as a
bare SHA-256 with no extension, which made the safety net unusable: putting a
picture back into a deck by hand means knowing which slide wanted it. Copies are
now named `<source> - slide NN - image N.ext`, numbered in deck order, with the
slide numbers zero-padded so the folder sorts the way the deck runs. A document
gets no page number, because nothing in a `.docx` manifest links an asset to a
page and its `pages` are section breaks rather than printed pages. The asset id
moves into the report beside the name, so a file in Drive can still be matched
to the manifest. Asked for by the human.


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
The container build passes and runs the C++ unit tests on a clean Ubuntu
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
reports NOT RUN ON CI rather than claiming a pass. 55 Python tests pass with
the fixture supplied; 22 skip without it. The C++ suite is now 107 tests.
The Publisher font audit (`docs/publisher-font-audit.md`) found that a `.pub`
yields font names only, except for embedded EOT fonts, and that PUB-001's
Sassoon names miss the shared service's keys -- a miss that currently also
prevents an automatic handwriting-font substitution.

#12 has merged. What remains unverified for Publisher is breadth, not depth:
only one real document has been parsed.

**Reading libmspub 0.1.4's source changed the picture (2026-09-23).** It never
calls `openGroup`, `startMasterPage`, the list callbacks, `openLink` or
`insertField`. It emits authored groups as layers, folds rotation and flips of
everything but text into the outline, paints master content into every page, and
calls `drawGraphicObject` only for BorderArt tiles. The parser now models all of
that (layers classified at close, rotation recovered from outlines, flips and
border art flagged), and the "a layer is never a group" decision is superseded.
See DECISIONS.md and `docs/publisher-parser.md`. **PUB-001 acceptance must be
re-run locally**, because its one layer is asserted to be a wrapper.
Lists, links and fields are not recoverable from a `.pub` at all through this
library.

Live OAuth, real Google conversion and visual fidelity remain unverified for
both PPTX and DOCX. Every Google interaction is covered by test doubles only.
No GCP resources are deployed.

The next milestone is a Google Cloud project. Note that verification does not
require Cloud Run: `config.py` permits `http://localhost`, so the app can be run
locally against a real OAuth client. Cloud Run, billing and a public hostname
are only needed to put it in front of staff.
