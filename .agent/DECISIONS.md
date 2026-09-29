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

