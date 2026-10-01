# Architecture decisions (append-only)

## 2026-09-22: Priorities and isolation
PPTX → Slides first, then DOCX → Docs, PUB → Slides, XLSX → Sheets.
Preserve src/ unchanged. Publisher-first scheduling in historical research is
superseded by the user's priority update and platform continuation instruction.

## 2026-09-22: First shared application
Use a Python FastAPI application, separate from Apps Script, with a source manifest
boundary and native Drive PPTX import. No custom PowerPoint renderer. Use per-job
temporary directories, a subprocess parser and bounded ZIP/XML processing.
Use Google user OAuth with drive.file, encrypted short-lived HttpOnly cookies,
state + PKCE and CSRF checks. No service-account document ownership, refresh tokens,
central token store or public asset sharing. A stable encryption key works across
Cloud Run instances; jobs remain synchronous and bounded. No deployment in this task.

## 2026-09-22: Stabilize before GCP setup
Keep GCP project creation, live OAuth and deployment after the local parser, API
boundaries and deterministic regression suite are solid. Mocked boundary tests must
reject malformed successful responses without exposing internals or losing recovery guidance.

## 2026-09-22: DOCX moves onto the platform, superseding "preserve src/"
The user has redirected the project: conversion runs as a Cloud Run service
covering all M365 formats, not as an Apps Script web app. This supersedes the
Apps Script preservation instruction in AGENTS.md and PROJECT.md section 26 for
new work. Apps Script PR #10 (floating tables) was closed unmerged; its branch
`feat/docx-floating-tables` is kept as the reference implementation and must not
be pruned. `src/` is untouched by this change.

## 2026-09-22: DOCX renders by rewriting the package, not by calling the Docs API
PPTX preflights and imports natively. DOCX does the same, but with a transform
step in between: the value of this converter is that it *rewrites* constructs
Google mishandles before Drive sees them. So the "Google Docs renderer" emits a
.docx aimed at Google's importer rather than calling the Docs API. It still obeys
section 4 -- it encodes what Google accepts, not why Word wrote the source.

## 2026-09-22: Google honours OOXML floating-table positioning
Verified against the live importer, not inferred. A table carrying <w:tblpPr>
with tblpX=7200, tblpY=2880 anchored to the page imported to exactly 5in from
the page left and 2in down, with text wrapping; tblpXSpec="right" with
horzAnchor="margin" landed flush right; a control table with no tblpPr stayed
inline. Consequence: a floating text box becomes a floating table and keeps both
its editable text and its position, instead of trading one for the other. This
is the single most load-bearing fact in the DOCX path.

## 2026-09-22: stdlib ElementTree for DOCX serialisation, not lxml
Parsing stays on defusedxml. Writing uses xml.etree with the conventional OOXML
prefixes registered, because mc:Ignorable names prefixes as text and renaming
them would leave that attribute pointing at prefixes that no longer exist.
Avoids adding a C extension to the container. Revisit if round-trip fidelity
proves insufficient.

## 2026-09-22: Package is parameterised by OOXML format
Every guard in package.py -- zip-bomb limits, traversal, symlinks, encryption,
duplicate names, macro detection -- is format-independent. Rather than copying
it per format, Package and validate_upload_name take a Format describing the
few things that differ (suffix, mime, main part, main mime, wording). Both
default to PPTX, so existing call sites are unchanged.

## 2026-09-22: mc:Fallback anchors are duplicates, not content
Word writes a shape twice: the modern form in mc:Choice and a legacy
restatement in mc:Fallback. Any pass that reads anchors must skip the fallback
copies or it double-counts every such shape -- and specifically makes a text
box's own fallback look like a separate picture positioned exactly beneath it,
which is indistinguishable from a genuine "card" layout.

This invalidates an earlier finding, recorded here rather than silently
corrected: the claim that two sample worksheets used a backing-picture pattern
for every text box was an artefact of counting fallback anchors. Measured
properly, 6 of 18 anchors in one and 4 of 15 in another are duplicates, and no
sample document contains a real backing picture. The behind-text handling is
still correct for documents that use the pattern; it simply does not fire on
this sample, so it remains unexercised by real data.

## 2026-09-22: Headers and footers are story parts, not decoration
word/header*.xml and word/footer*.xml carry the same constructs as the body --
anchored text boxes, legacy pictures, ink -- and Google mishandles them the same
way. They now get the identical transform. Branded letterheads and title blocks
live there, so converting the body while leaving the header broken is the worst
of both worlds. Their text is deliberately excluded from the verification token
count: Drive's plain-text export does not reliably include headers, so counting
them would report a mismatch on every document that has one.

## 2026-09-22: The full-page background heuristic is not ported
The Apps Script fixer detected full-page decorative images in headers by size
and page-aspect match, and deleted them. That existed because the old converter
flattened every picture inline, where a full-page background is ruinous. The
platform keeps pictures as floating anchors with their original position, so a
background can simply stay where it is. Deleting content on a size heuristic is
a worse trade than leaving it, now that leaving it works. Reconsider only if a
real conversion shows backgrounds breaking the result.

## 2026-09-22: VML lengths are read in every unit, not just points
The Apps Script version matched "pt" only and silently skipped anything else,
which loses the picture entirely. The port reads pt, in, cm, mm, pc and px. An
unmeasurable shape is left as-is rather than dropped: a picture we cannot resize
is still a picture.

## 2026-09-22: Four APIs, one scope
Enable the Drive, Slides, Docs and Sheets APIs in the Google Cloud project, but
keep the OAuth scope at drive.file alone.

Creating a Doc, Slide deck or Sheet needs only Drive: upload with the target
Google MIME type and Drive converts it. The other three APIs are for reading
back or editing what was created -- Slides is already used for PPTX read-back
verification, Docs would give DOCX a structural read-back instead of the
current plain-text export, Sheets is for future XLSX work.

All three accept drive.file for files the application created, so none of them
requires a broader grant. drive.file is non-sensitive; documents, presentations,
spreadsheets and full drive are sensitive or restricted and would widen what
staff consent to across their entire Drive. The application only ever touches
files it created, so the narrow scope is accurate rather than limiting.

## 2026-09-22: Publisher parser boundary
Read `.pub` through LibreOffice's libmspub, driving a small C++
`librevenge::RVNGDrawingInterface` sink that builds the intermediate model
directly. Do not write a new binary parser, and do not build production logic on
`pub2raw` text -- it is an unstable debug format that drops binary payloads.
The sink links librevenge only, not libmspub, so unit tests drive it with
synthetic property lists and no document is needed to test the adapter.

Support both image routes: `drawGraphicObject`, and a shape carrying a bitmap
fill. Confirmed on PUB-001 that `drawGraphicObject` is never called and all
twelve images arrive by the second route, so a parser watching only the obvious
callback would report that booklet as having no pictures at all.

Record `startLayer` as a rendering wrapper, never as an authored group;
librevenge emits it as a painting construct and treating it as a group invents
structure the author did not make.

Parser compatibility statuses are candidates (`basis: "parser-candidate"`),
never verified claims about Google rendering; the validator rejects a parser
bundle asserting otherwise. Geometry is normalised to PostScript points, with
the raw librevenge properties retained alongside so a renderer can revisit a
parser decision without re-reading the source. Do not vendor libmspub or
librevenge; tested against libmspub 0.1.4 and librevenge 0.0.5.

## 2026-09-23: Font substitution is shared, curated and reported
All source formats call one compatibility service. Parsers retain the original
family; they do not own replacement tables. A reviewed Google Fonts candidate
may be applied by a renderer only when it is not marked for manual review, and
every change records the original family, replacement, confidence and reason.
Unknown fonts stay unchanged instead of falling back silently. Google Fonts
catalogue membership is not treated as proof of availability in every Workspace
tenant. Accessibility-oriented choices require human review even when a reading
font candidate exists. PPTX applies safe mappings to a copy before native import;
DOCX and Publisher consume the same API when their owners complete integration.

## 2026-09-23: A layer can be an authored group (supersedes part of "Publisher parser boundary")
The 2026-09-22 entry said to record `startLayer` as a rendering wrapper, never as an
authored group. Reading libmspub 0.1.4's own source shows that is only half true.
libmspub never calls `openGroup`. It uses `startLayer` for two things: an authored
group (any shape with children opens a layer with no properties, paints each child,
then closes it), and one shape painted in several passes (border art, or any two of
stroke, fill and text), which carries `svg:clip-path` when the shape is cropped.
Under the old rule every real Publisher group was reported as an ignored wrapper.
Children were never lost, but the grouping was.

The parser now classifies each layer when it closes. A layer with a clip path stays
a wrapper. A layer with no properties becomes a probable authored group
(`type: "group"`, `container: {kind: "layer", isAuthoredGroup: true}`, with a
`probable-authored-group` warning stating the evidence) if it contains a nested
layer, which libmspub only produces inside a group, or if its children are not all
within the largest child's box plus a small tolerance. Everything else stays a
wrapper. The rule is conservative on purpose: a group whose largest child contains
the others stays a wrapper, losing the grouping but no content.

This was verified against library source, not against a real grouped document.
PUB-001's acceptance test asserts its one layer is a wrapper, and it must be re-run
locally. If that layer reclassifies, it is a finding to record deliberately, not a
number to edit.

## 2026-09-28: Add-from-Drive uses Google Picker, briefly exposing the OAuth
## access token to browser JS

The user asked for the tool to accept a file already in Drive, not only a
local upload. Google Picker is the standard way to do that, and Picker's own
integration model requires an OAuth access token in client-side JavaScript
to authenticate the picker iframe -- there is no server-side-only way to
drive it.

This is a real change from the existing posture (the OAuth access token has
never left this process before now, sealed in an encrypted HttpOnly cookie
-- see the 2026-09-22 "First shared application" decision). The scope is
kept as narrow as the tradeoff allows:

- The token is fetched fresh, on demand, only when "Add from Drive" is
  clicked (`GET /api/picker-token`), rather than embedded in the page on
  load. It sits in browser memory for as short a time as possible.
- It is still the same `drive.file`-scoped token the server already holds;
  Picker grants nothing broader, and picking a file grants per-file access
  under the same scope. No refresh token exists to leak (per the original
  decision) and nothing new is stored anywhere.
- The feature is opt-in per deployment via `GOOGLE_PICKER_API_KEY`
  (`config.py`'s `picker_ready`). Left unset -- true for every deployment
  today, since none has been created -- nothing about this is reachable:
  the button is hidden, the CSP stays maximally strict, and
  `/api/picker-token` refuses with `picker_unavailable`.
- The Content-Security-Policy only loosens (`script-src`, `frame-src`,
  `connect-src`) when the feature is actually configured, for the reason
  above.

**Not verified against a live deployment.** No GCP project exists in this
environment to test Picker against; the exact CSP origins Picker needs are
reasoned from Google's own documented integration, not observed. See the
warning in `docs/platform.md`.

## 2026-09-28: Add-from-Drive and the drive.file scope spike, verified live

The human provided access to the project's real GCP project
(`workspace-migration-toolkit`) and a Web application OAuth client
(`wmt-local-dev-web`, redirect `http://localhost:8080/auth/callback`) was
created for this. Superseding the "not verified against a live deployment"
caveat on the entry above and unblocking #53/#54's own live-scope-spike
requirement (CURRENT.md, "First run against live Google"), both run and
confirmed against real Google APIs, not reasoned from documentation:

- The full OAuth + PKCE + state sign-in flow works end to end against a real
  account.
- Add from Drive (this session's feature) works end to end -- Picker file
  selection, server-side download by id, preflight and native conversion --
  for both a `.docx` and a `.pptx`, once two bugs the design got wrong were
  fixed: a Website-restricted Picker API key breaks Picker (restrict to the
  Google Picker API only, not by referrer), and a `drive.file` per-file grant
  needs `PickerBuilder.setAppId()` with the OAuth client's Cloud project
  number, or a picked file downloads as unavailable even though Picker
  itself works. Both fixed; see `docs/platform.md` and `config.py`'s
  `picker_app_id`.
- The Content-Security-Policy needed `style-src 'unsafe-inline'`, not just
  the `script-src`/`frame-src`/`connect-src` already reasoned out: gapi's
  picker widget sets inline styles directly on this page, not only inside
  its iframe.
- **`documents.get` and `files.export` (PDF) both succeed under `drive.file`
  scope on a Google Doc this app itself created** -- confirmed directly
  against the Docs and Drive APIs with a real access token, on a real
  converted document. This is the exact question #53's "post-import checks"
  design and #54's "post-import repair" design were both blocked on. Neither
  is implemented yet; this only removes the reason they couldn't be started.

A temporary local OAuth client and API key were used for this, both created
in the GCP Console by the human, never entered as plain text by the
assistant -- the client secret was read from a downloaded JSON file, and the
short-lived access token used for the two API calls above was pasted by the
human from their own already-authenticated browser session, not obtained by
the assistant signing in. See CURRENT.md for what to do next.

## 2026-09-28: Remove the legacy Apps Script DOCX fixer, superseding its freeze
The Apps Script DOCX fixer (`src/`, previously frozen as a reference/fallback
per the 2026-09-22 decision above) is now removed from the repo entirely,
along with its Node regression suite (`tests/regression.test.cjs`) and every
doc reference to it (README.md, AGENTS.md, PROJECT.md, CONTRIBUTING.md,
docs/platform.md, docs/publisher-parser.md).

Rationale, from the user directly: keeping a second, worse DOCX converter
around only makes sense if someone would actually prefer it -- e.g. an
Apps-Script-only user who doesn't want to stand up the platform app. But the
Apps Script version had a known, already-diagnosed regression (it always
flattens floating text boxes to inline tables, losing position entirely,
even though the platform's own probe-document work confirmed Google Docs
honours OOXML floating-table positioning (`w:tblpPr`) and that fix was never
ported back). Given that gap, and that all further DOCX effort was already
committed to the platform per the 2026-09-22 decision, the user chose to
remove it rather than maintain it as a permanently-inferior parallel tool.

`Code.gs`'s git history (including the `feat/docx-floating-tables` reference
branch) still exists in this repo if the Apps Script approach is ever wanted
back; nothing was force-deleted from git history, only the working tree.
Any live Apps Script deployment already running at the trust is unaffected
by this repo change -- this removes the maintained source, not a running
service.

## 2026-09-28: Publisher → Google Slides, approved (PROJECT.md §38)
The human reviewed `docs/publisher-renderer-readiness.md` and made its open
decisions:

- **Route: build slides through the Slides API**, not IR → `.pptx` → native
  import. Chosen against the assistant's recommendation (which favoured
  reusing the import path), for the precise control over each element.
- **Images: a private Cloud Storage bucket and V4 signed URLs.** The Slides
  API's `createImage` accepts only "a publicly accessible URL" (checked in
  Google's reference and add-image guide, 2026-09-28), with no exception for
  Drive files; Google's own guide recommends Cloud Storage with signed URLs
  that expire in 15 minutes. Each image is uploaded, fetched once by Slides
  through a signed link, and deleted straight after; the bucket also carries a
  one-day delete rule as a backstop. Nothing is ever shared publicly in Drive.
  The bucket and the signing permission are the human's to create -- they are
  billable GCP resources -- and are documented, not created, by this repo.
- **Border art: composed into one image per border**, reported as FLATTENED
  (readiness §7.4).
- **Sassoon Primary → Andika**, applied automatically and reported. Andika is
  a Google font designed for early literacy (single-storey a and g). Owned by
  the shared font service; recorded here because the human made the call.
- **Master content: reported, not stripped** (readiness §7.5, the default).
- **Evidence: PUB-001 only for now.** Anything verified on that one file is
  labelled as such until PUB-002 onwards exist.

Build order: (1) accept `.pub` in the app with a working "Check file";
(2) the renderer, as pure IR → Slides requests, tested offline; (3) image
delivery and conversion; (4) a live run by the human with PUB-001.

## 2026-09-28: Publisher renderer defaults (step 2)
Judgement calls made while mapping the IR to Slides requests. Each one is
reported per element, and none is verified against Google until step 4.

- **Straight strokes with no filled area become editable lines**, one per
  segment, grouped. Pictures are kept for filled or curved drawings.
  PUB-001's only drawings are two ruled lines, and staff can edit a line;
  they can't edit a picture of one.
- **Pictures are stretched to their frames**, which is what Publisher's
  bitmap fill (`style:repeat: stretch`) and LibreOffice both do. The reader
  drops crops, so a heavily stretched picture is reported rather than
  guessed at.
- **A picture that can't be read leaves a dashed box saying so**, in its
  place on the slide, as well as the report line (§16). A gap in the layout
  would be missed.
- **Empty trailing paragraphs are dropped**; an empty paragraph in the
  middle keeps its font size so the spacing stays.
- **The first page's size is the presentation's**, and differing page sizes
  are reported, because Slides has one size per presentation.
- **Requests are grouped per page** so step 3 can sign picture links a page
  at a time within their 15-minute life.

## 2026-09-28: Publisher picture delivery (step 3)
How the approved bucket-and-signed-link route is built:

- **No key files.** The app acts as its own service account: from the
  metadata server on Cloud Run, or a developer's `gcloud` application-default
  login elsewhere. Links are signed by Google through IAM `signBlob`. A
  downloaded service-account key is refused: it is a long-lived secret on disk.
- **No new dependencies.** V4 signing is about 30 lines over `httpx`, and is
  tested against Google's published conformance cases.
- **One page at a time.** Store that page's pictures, sign 15-minute links,
  send the page, and delete the copies in a `finally`. Links live seconds in
  practice. The bucket's one-day lifecycle rule is the backstop.
- **Two identities, kept apart.** The person's `drive.file` token creates
  and edits the presentation. The app's account only touches the bucket.
- **Nothing that could carry a link is reported.** Only the index of a
  refused request is read from a Slides error; its text is never kept.
- **A refused picture becomes the marked box** from step 2, and the page is
  sent again, rather than the page being lost.
- **Convert appears only where a bucket is configured.** `describe()`
  now takes the settings, so a deployment without one still offers Check.

## 2026-09-29: A Publisher conversion starts from an imported deck
PROJECT.md §14 asked how Slides can be made at a publication's own size.
The live run answered it. `presentations.create` accepts a `pageSize` and
ignores it: A5 came back as 720 × 405 pt, Slides' default. Google's
PowerPoint import does keep a deck's own size. So the converter uploads an
empty one-slide `.pptx` of the publication's size (`publisher_deck.py`,
written by hand, so nothing in it comes from a template), with conversion to
Slides. It then builds the pages into that presentation through the API as
before, and deletes the deck's own slide. Verified live with PUB-001: A5
portrait kept.

## 2026-09-28: Excel source format and non-worksheet sheets (#51)

Keep the worker package byte-for-byte in its source format. A macro-enabled
container without VBA is not renamed to XLSX: check import capability and upload
using XLSM's own MIME type and emitted path. Actual VBA still blocks native import.

Chart sheets are retained in the source package and inventoried with an
UNSUPPORTED review finding; no verified layout/editability claim is made.
Dialog sheets and both Excel macro-sheet variants require manual migration,
including when no VBA project exists. Never execute or translate their automation.
These are unsupported capabilities, not deliberate content omissions (IGNORED).
Read-back does not demand grid semantics from source chart sheets.

The manifest intentionally retains sheet names and external workbook filenames
for verification/dependency matching. Web workspaces are temporary; CLI output
retains the manifest and must be treated as document data. Reports omit those
names, values, formula expressions and macro source. The earlier content-free,
ephemeral-only manifest wording was inaccurate and is superseded here.

## 2026-09-29: Fit substituted text to its frame: spacing first, then size
The live run showed Andika text running off PUB-001's pages. Andika's
letters are wider than Sassoon's, so the same text wraps onto more lines.
Each text frame is now laid out offline with Andika's real advance widths
before the requests are written.

- **Google's own geometry, measured, not the font's.** On the live slides,
  Google spaced lines 1.2 times the font size apart at 100% (Andika's
  metrics say 1.61), and kept 7.2 pt inside the box at the sides. A first
  version used the font's 1.61 and overcorrected. The first version was
  measured, fixed and re-run the same day: page 2's last line then landed
  within 2 pt of the estimate.
- **Line spacing is tightened first**, to no less than 90%, then **the text
  is made smaller**, evenly, to no less than 75%, rounded to half points.
  Young readers need the letters large more than the lines far apart.
- **Every change is reported per frame**, and so is text that still won't fit.
  A font without shipped measurements is left untouched.
- **Measurements, not fonts.** `scripts/font_metrics.py` extracts advance
  widths from Google Fonts' files into JSON. No font binary enters the
  repository.
- **Hand-made line breaks are kept**, even where the new font leaves a word
  on its own line: they are the author's.

## 2026-09-29: Publisher tables are drawn without borders
libmspub 0.1.4 passes on no table borders at all: its `TableInfo` holds row
heights, column widths and cell spans, and it writes nothing else per cell
(`MSPUBCollector.cpp`, checked in the 0.1.4 source). So whether a Publisher
table had lines can't be known from the reader. The renderer makes every
border transparent (Slides has no "no border"), which is how LibreOffice
draws such tables and how PUB-001 looks, instead of leaving Google's default
grey grid. The report says so and tells staff to add borders if the original
had them. Reading real borders from the `.pub` belongs with the picture-crop
investigation, which needs the same direct reading of the file. Verified live
on PUB-001.

## 2026-09-29: Recover picture crops from Publisher's drawing records
PUB-001's stretched pictures were cropped in Publisher. The crops are the
Office drawing properties "crop from top/bottom/left/right" (0x100 to 0x103)
on each picture shape in `Escher/EscherStm`. libmspub 0.1.4 reads every shape
property into a map and never looks those four up (checked in its source).

- **The parser keeps the records as they are** (`drawing.bin`), read
  through librevenge from the container libmspub has just accepted and held
  to the per-asset limit. It gets no new parsing code and no new dependency.
  The records are small (11 KB for PUB-001) and hold no text or picture data.
- **The app interprets them** (`publisher_crop.py`, in the worker): stored
  pictures are matched to assets by size, and placements to shapes in
  whichever order fits.
- **A crop is applied only when the cropped picture has its frame's shape**,
  within 3%. That is the purpose of a crop, and it guards against any
  mismatch. On PUB-001 all five fit exactly, including one picture cropped
  two different ways.
- The same records hold other properties libmspub drops. They are the
  place to look next for anything the reader loses (not table borders,
  which live in the Contents stream).

## 2026-09-29: Wrap text around pictures with paragraph indents
Google Slides has no text wrapping. The human chose, from three options,
per-paragraph indents over splitting text into several boxes (which breaks
the flow for editing) or leaving the overlaps.

- **What wraps:** a picture or shape drawn in front of a text frame and
  overlapping it. This is Publisher's default, and what PUB-001 shows. The
  reader doesn't pass on each object's wrap setting, and objects behind the
  text are left alone.
- **How:** each paragraph level with it gets a start or end indent (on the
  picture's side) that clears it by 3.6 pt, computed with the fitting layout.
  Indents and fitting are repeated until stable, and an author's own indent
  is never added to.
- **Limits, reported:** the whole paragraph moves; text keeps to one side;
  a picture across more than 60% of the line stays over the text.
- Verified live on PUB-001, pages 2 and 3.

## 2026-09-29: WordArt is recovered as editable text
The human compared PUB-001 in Publisher with the conversion. The title
"Early Reading at St.Vincent's" is WordArt, and libmspub passes WordArt on
only as outlines (a zero-area gradient shape and one baseline per line), so
the conversion showed two purple lines and no words. The words, font (Sassoon
Primary), size (44 pt), bold and colour (#8064a2) are the WordArt shape's
Office drawing properties, in the records the crops already come from.

Each WordArt is matched to its outline layer by the outline's colour, in
drawing order, and drawn as a centred text box as large as fits. The outlines
are left out. Effects are reported, not faked, and a WordArt with nowhere to
go is reported with its words.

Two parallel sessions built this at once in one checkout. The surviving
module (`publisher_wordart.py`, `placed()`) is the one that reports unplaced
WordArt, and the renderer wiring was fitted to it.

## 2026-09-29: XLSX extent, indexes and abandoned workspace cleanup

Google's workbook cell-limit preflight uses the bounding extent of actual `<c>`
cell references, not SpreadsheetML's cached `<dimension>`. Some exporters leave
that cache at the full Excel grid after cells are removed, causing a false hard
block. Keep the declared extent as a separate diagnostic: when it alone exceeds
Google's limit, report `declared_extent_needs_review` and allow native import.

XLSX sheet indexes are zero-based, matching other toolkit manifests and list/API
positions. User-facing messages may describe ordinal sheet numbers separately.

Remove the uncalled stale-workspace sweeper. The context manager still removes
normal request workspaces. Cleanup after process or host termination belongs to
the deployment's ephemeral-storage lifecycle; an application helper that no
startup or scheduler invokes creates a false cleanup guarantee.

## 2026-09-29: XLSX native import verified live

A generated five-sheet XLSX was analysed and converted through the running app
against real Google Drive and Sheets APIs. The source SHA-256 in the downloaded
conversion report matched the generated fixture. Drive created a native Google
Sheet and archived the original; Sheets read-back confirmed five sheet names,
GRID types and visibility states. The source inventory recorded 227 populated
cells, 47 formulas and no formula-error cells.

This verifies the OAuth scope, Drive import and Sheets structural read-back path.
It does not establish formula, chart, formatting, validation or protection
fidelity; the report correctly retains `workbook_review_required` for those.


## 2026-09-29: No "Check file" button in the final version (owner)

The owner does not want the separate "Check file" step in the version staff
use: its summary is hard for an end user to understand, and it adds a click
before the conversion they came for. It stays for now, while the conversions
are tested with an agent watching. Before release, the app converts in one
step, and whatever Check told the user (pages, fonts, what will not survive)
belongs in the conversion report instead. This touches every format, so it is
done once for all of them, including the source fingerprint check that Convert
currently takes from Check. Until then, Check must stay cheap: for Publisher
it should only read the file, not plan the slides.

## 2026-09-29: Build libmspub with our own patches (route A)

libmspub 0.1.4 parses paragraph lists and never passes them on, and has had
no release since. The owner chose to build it from LibreOffice's release
tarball (checked by SHA-256) with a small patch set kept in
`native/pub-parser/libmspub/patches`, installed into a private prefix the
parser links by run path. Only the patches live here, never libmspub's
source. Every build (the app image, docker/publisher.Dockerfile, CI) uses
the same script, and `--version` names the patches applied. Further gaps
libmspub parses but drops, or never parses (table borders), are to be closed
the same way, one patch each, rather than by re-reading the file beside it.

## 2026-09-29: Table grids, and pictures set in text

**Grid.** No table in PUB-001 or PUB-002 stores a border setting in any
record (Contents table and cell records, the text's TCD records and the
drawing records, all dumped with a debug build of libmspub). Yet every table
in both prints a thin black grid, as the owner's print previews show. So
tables are drawn with Publisher's default grid (0.75 pt black), replacing the
invisible borders of #95. A table with authored lines has not been seen; its
records will show where Publisher keeps them.

**Inline pictures.** A picture set in a line of text belongs to a Contents
record that is not a page, so libmspub never draws it. Its text keeps U+FFFC,
and the picture stays in the drawing records. Getting it through libmspub
would mean a patch that invents inline objects in its text stream, which
librevenge has no settled form for. Instead, the parser keeps the stored
pictures stream as it keeps the drawing records, and the app pairs marks with
unplaced picture shapes. That qualifies route A's "one patch each": where
libmspub has no model for a thing at all, reading Publisher's own records
beside it (as for crops and WordArt) is the smaller change.

## 2026-09-29: Keep tables on the page, readable text first (owner)

Slides grows table rows to their text, so Publisher tables laid out Google's
way ran off the page (PUB-002 pages 3, 7, 8, 9). A table may now grow into
free space below it: down to whatever is below, the bottom of a box it sits
in, or 10 pt from the page edge. Only past that is its text set closer, then
smaller, to the same floors as a text box (90% spacing, 75% size). The owner
chose readable text over Publisher's exact bottom edge, so a table may pass a
border it overhung in Publisher. Calibri and Arial are now measured (from
their metric-compatible open fonts, Carlito and Liberation Sans), so text
boxes in them are fitted too. Every one of those that shrinks on PUB-002 was
measured live as overflowing its box before.

## 2026-09-29: Built for a frustrated educator, not for review (owner)

The people this is for are teachers whose files did not survive the move to
Google. They need: choose a file (upload, or from Drive), press Convert, get
the Google file. They do not need notes. The owner also wants a bulk option:
convert a whole folder of files that don't play nicely with Google in one go.

So, for the staff-facing app:
- one step: pick, then Convert (no Check file button, as already decided);
- no lists of notes or warnings on screen. The notes are still wanted, for
  testing and refining the conversions: every note stays in the report saved
  in the conversion folder ("Conversion report.json"), which is where the
  owner and agents read them. Always ask first what the end user needs;
- bulk conversion of many files at once is a goal.

Until the one-step app lands, the reader's own notes (libmspub and parser
diagnostics) are kept out of every on-screen summary and kept only in the
technical report (`technicalNotes`, and each element's notes marked
`source: reader`). Bulk conversion must respect the drive.file scope: the app
can only open files the person picked, so "a folder" means picking many files
from it in the Picker (multi-select), not reading a folder's contents, unless
a broader Drive scope is deliberately chosen (it needs Google's verification).

## 2026-09-30: A picture joins a positioned table only on a shown common page (#134)

Page coordinates repeat on every page, so the geometry pass (#55) moved a
picture on one page into a table at the same spot on another. A picture and
a table now count as on one page only when nothing between them ends a page
(a page break, a paragraph set to start a page, a section break that is not
continuous, or Word's own `w:lastRenderedPageBreak`). Where Word's record of
its pages is absent, that is not enough on its own: nothing marks where a
page ends in running text, so they must also be within three blocks of each
other (`MAX_BLOCKS_APART`). Three is an unmeasured default, chosen because a
picture beyond it is left in place and reported, never lost; revisit it
against real worksheets. A page end inside either one, or too great a distance, leaves the
picture floating and counts it in `picturesGeometryUncertain`, which now
reaches the saved report (it was dropped before). The order-based pass
refuses a run of pictures with a page break inside it.

## 2026-09-30: Margin strips, page-sided frames, and each table's own section (#112, #115, #135)

**Margin strips.** Word's `leftMargin`/`topMargin` frames start at the
paper's edge and `rightMargin`/`bottomMargin` where the text area ends
(ECMA-376 20.4.3.4/5). They were all treated as the text area. They are now
restated as page offsets from the governing section's page size and margins,
in one helper the parser and the placement passes share.

**Inside and outside.** These swap sides between odd and even pages, and the
page an object lands on is not known. Reading them as on an odd page would
trade one wrong placement for another, and dropping the position would lose
the object's place entirely. The owner chose: keep the position they get
today (against the text area), and report it as uncertain
(`positionsPageSideUncertain` in the conversion report, a
`position_page_side_uncertain` warning in the analysis).

**Sections.** Every table, row and placement is measured by the section
that lays it out (the first section break at or after it, else the body's
own `w:sectPr`), never the last section for everything, and never the old
properties a tracked change keeps. This supersedes "measured by its last
one" in `_final_section`'s docstring, which now serves only headers and
footers: which sections use a header is not worked out, so a header is
measured by the body's last section.

## 2026-09-28: Deploy to europe-west2 (London), stated on the frontend for DPO review
Cloud Run deployment (when it happens) will use `europe-west2`. The user's
reasoning: a school's DPO reviewing this for sensitive materials will want
UK data residency during processing, and the frontend disclaimer now states
this directly, alongside "never stored" and "no AI/LLM involvement".

Scope of the claim matters and is worded carefully: this app never persists
anything itself (see the 2026-09-22 OAuth decision -- no document/token
database, per-job temp workspace deleted after each operation), so
`europe-west2` bounds where transient *processing* happens, which is the
whole data-residency surface this app controls. Where the *converted file
itself* ends up living is Google Drive storage, governed by the trust's own
Google Workspace data-location policy, not by this app -- the disclaimer
says "processed" / "converts", not "stored", specifically to avoid
overclaiming a guarantee this service doesn't provide.

`deploy/cloud-run.example.yaml` and `docs/platform.md` now name the region
explicitly instead of leaving it as an unstated placeholder. No GCP
resources were created by this change -- it is a deployment intention
recorded ahead of the actual Cloud Run setup work (see the outstanding
GCP-setup checklist in HANDOFF.md).

## 2026-09-30: Read the converted Word document back, into the report only (#53)

After a Word conversion, the app reads the new Google Doc (`documents.get`,
every tab) and exports it as a PDF, then applies fixed rules: pictures still
floating, top-level tables lost against what was uploaded, paragraphs that
only break a page, a page count unlike the one Word saved in
`docProps/app.xml`, and pages that draw no text and no picture.

- **Report only.** The findings go into the saved conversion report under
  `readBack`, not into `warnings`, which the screen shows (see "Built for a
  frustrated educator"). They carry counts and page numbers, never text.
- **Never a failure.** The conversion has already worked when these run. A
  read Google refuses, or a PDF that can't be read, is recorded under
  `readBack.unavailable` and the status is unchanged.
- **Our own small PDF reader, not a dependency.** Only the page tree and each
  page's content stream are read, Flate only, with sizes capped. A page it
  can't decode is never called blank; a PDF it can't read gives no page
  findings rather than a count of zero.
- **Word's page count is evidence, not a rule.** It is Word's own last
  layout, and other programs may not write it.
- **Not verified live.** Tested against a fake Google and PDFs built in the
  tests; the scope spike above showed `drive.file` reaches both calls, not
  what real answers look like for real worksheets. PPTX and Sheets read-back
  are left for later.

## 2026-09-30: Blank-page repair after import is optional, off by default (#54)

Owner and Claude 1 agreed. Google's import can turn Word's empty separator
paragraphs into blank pages. #42 (already fixed) keeps those paragraphs
rather than deleting them before import, which would join pages and lose
spacing. #54 instead repairs them in the new Google Doc.

- **Off unless `WMT_DOCX_REPAIR_BLANK_PAGES` is set.** It edits the
  person's document after it is made, and `documents.batchUpdate` under
  `drive.file` has not been verified live. The live scope check above covered
  only reading.
- **Only when the read-back (#53) found probably-blank pages**, and only on
  empty top-level paragraphs that sit directly between two tables or hold a
  page break. Never the body's last block, never inside a table, never a
  paragraph with content. The Docs API can't say which page a paragraph is on,
  so candidates aren't matched to particular blank pages; the report gives the
  page counts and blank pages before and after instead.
- **One update, guarded by `requiredRevisionId`** from a fresh read whose
  indexes are the only ones used. If anyone changed the document in between,
  Google refuses the whole update, and the repair is reported as skipped.
- **Idempotent.** A paragraph already at 1 pt with no keep-together or
  spacing isn't a candidate, so a second run changes nothing.
- **Reported, not shown:** `readBack.repair`, classified SUBSTITUTED.

## 2026-10-01: Converted Sheets use the UK locale and the person's time zone

Owner's decision. A nursery calculator typed its dates of birth as text
("31/07/2023"). UK Excel reads that as 31 July. A Google Sheet in a US locale
reads it as no date at all, and every formula built on those dates gave
`#VALUE!`.

- **Locale: always `en_GB`.** This is a UK-schools tool. The locale decides how
  typed dates are read, so it doesn't follow the browser: a teacher on a
  US-English laptop at a UK school would get the wrong dates.
- **Time zone: the person's own,** sent by the browser
  (`Intl.DateTimeFormat().resolvedOptions().timeZone`, header `X-Time-Zone`).
  `TODAY()` and `NOW()` then follow their day. The server only accepts a name
  shaped like an IANA zone. If there is none, or Google refuses it, the Sheet
  gets `Europe/London`. If neither can be set, the Sheet still converts and the
  report says `locale_not_set`.
- **Set after import,** with one `spreadsheets.batchUpdate`
  (`updateSpreadsheetProperties`) on the Sheet the app has just made. That
  works under `drive.file` and needs no new permission. Recorded in the
  report as `spreadsheetSettings`.
- **Dates typed as text are counted, never quoted:** `dates_stored_as_text`,
  with a count and sheet indexes only. The UK locale lets formulas read them,
  but they don't sort or filter as dates, so the note asks for them to be
  retyped.
