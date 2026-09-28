# Current state

A snapshot, not a log. Rewritten 28 September 2026 -- the previous version
was a narrative changelog back to 22 September that had mostly gone stale
(every item in it is now merged, superseded or answered). For the history
of how it got here, see git log and merged PR descriptions; `HANDOFF.md`
keeps the last few session handoffs, `HANDOFF-archive.md` the rest.

## Coordination

The human runs this as the conductor: they relay prompts between whichever
sessions are working the repo at a given time (this session, "Codex", a
second Claude Code instance) and copy-paste text between them -- there is no
live cross-session channel, so don't assume another session will see a
message you didn't put in a PR, an issue comment, or a coordination file.
Agent-mail has not been reliably available; issues are claimed by GitHub
comment instead. All work lands as a PR the human merges; nothing merges
itself.

No merging without the human's approval on anything that isn't yours to
merge. Nothing claims live Google behaviour without it being verified
against a real deployment. No GCP resources, keys or billable resources. No
real documents, extracted contents, credentials or tokens are ever
committed.

## Who owns what

| Area | Owner | Notes |
|---|---|---|
| `app/workspace_toolkit/docx.py`, `docs.py`, `pipelines.py`, `tests/platform/test_docx*.py` | DOCX stream | This session, most recently |
| Everything else under `app/`, `deploy/`, `config.py` | Platform stream | |
| `native/pub-parser/`, Publisher-owned Python | Publisher stream | |
| `rescue/xlsx-sheets-mvp` and XLSX | XLSX stream ("Codex") | PR #72 open, draft |
| `src/` (legacy Apps Script fixer) | Frozen | No further work planned; 19 Node regression tests still pass; stays deployed for staff use |

Do not edit another stream's files without saying so in your handoff entry.

## Where things actually stand

**DOCX** is the most active stream. `main` carries the parser, Google Docs
renderer, and web/job/Drive wiring; a `.docx` converts by the same route as
a `.pptx` through a pipeline registry. Recently landed: font-theme
resolution now matches spec precedence (#49), section counting ignores
tracked-change history and reaches into content controls, header/footer
content is now counted in the preflight report (was silently skipped), a
row that gains a picture from the floating-picture-inlining pass is
protected from splitting across a page break, and pictures stacked across
several consecutive paragraphs above a table (not just the last one) are
now placed into their cells. Still open: #53 (post-import Docs
API/PDF read-back) and #54 (fixing blank pages from separator paragraphs)
are both explicitly design-only and blocked on verifying, against a live
Google test tenant, whether `drive.file` scope reaches `documents.get` and
`files.export` on a file the app itself created -- nobody has done that
spike yet. #55's fully general geometry case (a picture anchored anywhere,
placed by rectangle overlap against a table's own `tblpPr`/`tblInd`
position and stated row heights) is still open; most real worksheets lack
the explicit positioning or row heights to make that case computable
without guessing.

**#36** (accept files over 25MB) looked like a config change but isn't:
proper "no fixed limit" needs chunked/resumable upload, object storage
instead of local disk, background jobs instead of one synchronous request,
and verification against Google's own actual limits on a live deployment.
Don't pick this up expecting a quick fix.

**Publisher** (`native/pub-parser/`) has its native libmspub adapter and
intermediate model merged (was PR #12). PUB-001 (a real school booklet,
never committed) is the only real document parsed so far and its
acceptance passed after the "a layer is never a group" heuristic was
superseded by reading libmspub 0.1.4's actual source -- see DECISIONS.md.
Groups are inferred (never authored explicitly by the library), master
content is duplicated per page, crops are unapplied, border art becomes
many separate images, and lists/links/fields are not recoverable from a
`.pub` through this library at all. Breadth, not depth, is what's missing:
more real `.pub` documents with grouping, rotation, flips and border art
would be the highest-value thing to get. No Slides renderer for Publisher
yet -- PROJECT.md section 38 is an explicit stop point until the breadth
work above is further along.

**Platform / PPTX** carries the shared FastAPI app, PPTX preflight and
native import, and the shared font-substitution catalogue (PPTX applies
MEDIUM-confidence candidates automatically; DOCX applies HIGH only -- an
intentional difference, see `docs/publisher-font-audit.md`). #52's audit
is fully resolved: seven low-severity findings fixed directly, the
library-folder race (#70, two concurrent conversions could each create a
"Workspace conversions" folder) fixed with a lock plus re-check, the DOCX
header/footer finding fixed, and one wasn't applicable.

**XLSX** has a working MVP on `rescue/xlsx-sheets-mvp` (PR #72, draft) --
fixes a `.xlsm` upload crash and chart-sheet rejection from #51 -- with a
few smaller follow-ups (cell-limit estimate, one-based sheet indexes, an
unused sweeper) still to be resolved or split out before it's ready for
review.

**Unverified everywhere**: live OAuth, real Google conversion and visual
fidelity for PPTX, DOCX and Publisher alike. Every Google interaction in
the test suite is a test double. No GCP resources are deployed. The next
real milestone for any of this is a Google Cloud test project -- note that
verification doesn't need Cloud Run: `config.py` permits `http://localhost`,
so the app can be run locally against a real OAuth client. Cloud Run,
billing and a public hostname are only needed to put it in front of staff.
