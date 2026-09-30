# Current state

Issue #51's blocking defects are merged on main in `77e08cb` (#72). Follow-up
work is on `codex/xlsx-live-followups`: cell-limit checks now use observed cell
extent while reporting stale declared extents, sheet indexes are zero-based, and
the unused workspace sweeper is removed. Local checks pass. Live native import
was verified on 2026-09-29 with a generated five-sheet workbook: Drive creation
and Sheets structural read-back succeeded. Visual fidelity remains a human review.

A snapshot, not a log. Rewritten 28 September 2026 -- the previous version
was a narrative changelog back to 22 September that had mostly gone stale
(every item in it is now merged, superseded or answered). For the history
of how it got here, see git log and merged PR descriptions; `HANDOFF.md`
keeps the last few session handoffs, `HANDOFF-archive.md` the rest.

## Audit fixes (2026-09-30)

The full-repository audit's issues are #105-#137 (plus #55, reopened). Fixes are split by stream: Publisher (#105-#111) on `fix/publisher-planning-crashes` and after, DOCX (#113-#117, #134, #135, #55) in a second Claude Code session. Issues are claimed by comment before work starts.

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
| Legacy Apps Script fixer | Removed | Source deleted from the repo 2026-09-28 (see DECISIONS.md); DOCX work happens on the platform |

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
now placed into their cells, and (#55, now closed) so is a picture anchored
anywhere in the document, by rectangle geometry against a table's own
`tblpPr` position and stated row heights, for the minority of tables exact
enough to measure that way.

Still open: #53 (post-import Docs API/PDF read-back) and #54 (fixing blank
pages from separator paragraphs) are both still design-only, but **no
longer blocked**: the live scope spike they were waiting on ran on
2026-09-28 against the project's real GCP project, and `drive.file` scope
does reach both `documents.get` and `files.export` (PDF) on a Google Doc the
app itself created -- see DECISIONS.md's 2026-09-28 entry. Neither issue is
implemented yet; this only removes the reason neither could be started.

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

**Add from Drive** (PR #81) adds Google Picker as a second, opt-in source
for a file to convert, alongside the existing local upload -- the server
downloads a picked file itself by id rather than the browser sending it
twice. Opt-in per deployment via `GOOGLE_PICKER_API_KEY`; unset, the app
behaves exactly as before. Verified live 2026-09-28, see `docs/platform.md`
and the 2026-09-28 DECISIONS.md entries for what the reasoned design got
wrong and how it was fixed.

**The GCP project exists** (`workspace-migration-toolkit`) and a Web OAuth
client works against it -- this is new as of 2026-09-28; earlier notes in
this file and in issues saying "no GCP resources exist" are stale. What's
now actually verified live: the OAuth + PKCE sign-in flow; a real PPTX and a
real DOCX converting end to end (both via local upload and via Add from
Drive); Slides read-back verification (page size, count, text); and
`drive.file` reaching `documents.get`/`files.export` on an app-created file
(see #53/#54 above). **Still unverified**: visual fidelity (nobody has
compared a converted document's actual rendering against the source, which
is #53's own "read the converted document back" point), Publisher's Slides
path (no renderer exists yet), and anything at Cloud Run/production scale --
this was all run locally against `http://localhost:8080`, which `config.py`
permits for exactly this reason. No billable resources beyond the free-tier
API usage from this session were created.
