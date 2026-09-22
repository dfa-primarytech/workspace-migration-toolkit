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
