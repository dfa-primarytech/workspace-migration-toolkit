# Excel to Google Sheets migration

## MVP boundary

The Excel path uses Google Drive's native import for ordinary Excel workbooks.
The worker first validates and inventories the OOXML package without network
credentials, then copies the package byte-for-byte to `converted.xlsx` or
`converted.xlsm`, retaining the source format. Import capability is checked
against that format's MIME type, which is also used for upload. This
preserves formulas and workbook structures for the native importer rather than
attempting to reinterpret them in Python.

Live native import was verified on 29 September 2026 with a generated five-sheet
workbook: Drive created the Google Sheet and Sheets read-back confirmed all five
sheet names, grid types and visibility states. The source contained 227 populated
cells and 47 formulas with no source formula errors. Formula results, formatting,
charts, pivots, validation and protection still require human visual review; this
single synthetic import is deployment evidence, not a general fidelity claim.

## Batch model and dependencies

A batch contains one `WorkbookJob` per workbook. Each job has an idempotency
key derived from its source digest, an attempt counter and explicit status.
Retry changes state but never silently repeats a Google create operation after
an uncertain response.

Preflight records sheet names and external workbook target filenames in the
manifest. Web jobs delete that manifest with the temporary workspace; the offline
CLI retains it in the output directory requested by its caller. Treat that output
as document data, not a shareable diagnostic report. The batch planner matches
external filenames to other files uploaded in the
same batch, detects cycles and can map resolved targets to destination Drive
IDs after their jobs finish. Conversion reports expose counts and findings,
not filenames, formulas or cell contents. This MVP does not rewrite Excel
external-link formulas: unresolved links and cycles require manual migration;
resolved links remain a review item until an authorised link-rewrite stage is
implemented and tested.

## Limits and escalation

Preflight enforces the package's compressed and expanded ZIP limits and checks
the Google Sheets limits of 10 million cells per spreadsheet, 18,278 columns
and 50,000 characters per cell. Grid-size checks use the furthest actual cell
reference in each worksheet rather than SpreadsheetML's cached `<dimension>`,
which exporters can leave at the full Excel grid after content is removed. The
declared extent is retained separately; an over-limit declaration with an
in-limit observed extent produces an explicit review finding instead of blocking
conversion. It inventories formulas by storage type,
formula error cells, charts, pivots, queries, connections, controls, embedded
objects, protection, hidden sheets, defined names and external workbook links.

Per-file outcomes are:

- `converted`: no preflight or read-back finding (the read-back currently
  always asks for visual review, so this is reserved for stronger verification)
- `converted_with_review`: native import completed with review findings
- `manual_migration_required`: a known limit or unsupported automation/data
  feature prevents safe automatic conversion

Macro-enabled workbooks convert (DECISIONS.md, 2026-10-01). Google converts no
`.xlsm` at all: in the live test Drive listed no import for its type. So the
worker writes every workbook again as a plain `.xlsx` (`macros.macro_free`):
- the macro project and every relationship, override and default that declares
  it are taken out;
- the workbook part is declared as an ordinary workbook;
- the result is opened again as an `.xlsx` before it is used.

If that can't be done safely, the workbook needs moving by hand
(`macros_not_removable`). The original `.xlsm`, macros and all, is archived in
the person's folder as before.

The macros are read (`vba.py`, following [MS-CFB] and [MS-OVBA], with limits)
but never run. Their source is saved as text in the person's own conversion
folder, and recorded macros are written as Apps Script beside it
(`apps_script.py`). Neither file is logged or placed in the report, which gets
counts only: `macroCode` in the manifest, and one of `macros_translated`,
`macros_partly_translated`, `macros_not_translated` or `macros_unreadable` as a
finding.

Chart sheets are inventoried separately from worksheet grids and preserved in
the source package. They remain `UNSUPPORTED` findings requiring review: the
tool does not establish whether their layout or editability survives import.
They do not reject an otherwise convertible workbook. Read-back counts all sheets
but requires an editable grid only for source worksheets.

Dialog sheets and Excel macro sheets (including international macro sheets) are
also inventoried and preserved. They require manual migration even without a VBA
project. Macro-sheet automation is never executed or translated. These are
`UNSUPPORTED`, not `IGNORED`: the tool cannot safely represent their behaviour.
Missing, external or mismatched sheet references still produce explicit errors.
Sheet indexes in manifests and findings are zero-based, matching the other source
formats and API-facing collections in the toolkit.

The sheet kinds follow Microsoft's
[SpreadsheetML sheet documentation](https://learn.microsoft.com/en-us/office/open-xml/spreadsheet/working-with-sheets)
and [Office macro-format specification](https://officeprotocoldoc.z19.web.core.windows.net/files/MS-OFFMACRO/%5BMS-OFFMACRO%5D.pdf).
This describes source structure, not verified Google import behaviour.

The Apps Script is bounded to what Excel's macro recorder writes:
- select, fill down, copy and paste, clear;
- set a value or formula, bold, italic, underline, font, colour and fill;
- switch sheet, insert or delete rows, columns or cells;
- show a message.

Window-only steps such as scrolling are dropped. Any other line is kept as a
"Not translated" comment and counted, never guessed at. The script adds a
Macros menu.

When the person allowed Apps Script at sign-in, the app adds the script to the
Sheet itself (`script_projects.attach`), with the macros declared as Google
Sheets macros under Extensions → Macros (DECISIONS.md, 2026-10-01). Otherwise,
or if Google refuses (most often the per-person Apps Script API setting), the
person pastes it in under Extensions → Apps Script, as the report explains.
No project is created without that permission, and the source never goes in a
report. General VBA translation (variables, loops, conditions, events) remains
out of scope.

Macro buttons (`buttons.py`): Google brings an Excel shape across as a drawing
but drops the macro it ran, and only Apps Script can set one
(`Drawing.setOnAction`). Each shape on a worksheet is read with its sheet,
anchor cell, label and assigned macro. A shape is linked to the macro Excel
assigned it. With none, which is how a workbook that has been through Google
before comes back, it is linked only when the workbook has exactly one macro
and the label begins with that macro's name in whole words ("Repair Columns"
runs `Repair`). The script's `onOpen` links them when the Sheet opens, leaving
any drawing that already has a script alone. A sheet with one drawing and one
button is matched without its anchor; otherwise the anchor cell must agree.
The report counts linked buttons (`macro_buttons_linked`) and buttons left to
redo (`macro_buttons_not_linked`): those assigned a macro that isn't there,
and Excel form-control buttons, which Google drops on import. It never gives
their labels.

## Locale, time zone and text dates

Every converted Sheet is set to the UK locale (`en_GB`) and to the person's
own time zone, from their browser, or `Europe/London` (DECISIONS.md,
2026-10-01). Without that, a Sheet in a US locale reads a date typed as text,
such as "31/07/2023", as no date at all, and formulas built on it give
`#VALUE!`. The preflight counts those cells (`textDates`,
`dates_stored_as_text`) without reading their text into the manifest or the
report.

## Data lifecycle

1. The web request creates an isolated `wmt-*` temporary directory for one
   workbook.
2. The credential-free worker validates the package and writes a structural,
   temporary manifest. It serialises no cell values, formula expressions or
   VBA source. A macro workbook's source and its Apps Script are written as two
   files in the temporary workspace, for upload to the person's own folder only.
3. Conversion creates a private folder in the user's Drive. By default the
   original workbook is archived there before native import. The
   `delete_after_conversion` policy hook skips that archive for deployments
   whose retention policy requires deletion.
4. The returned and uploaded report contains counts, statuses and review
   findings only.
5. The workspace context deletes all local source, manifest and worker output
on success or failure. Crash recovery for directories left by a terminated
process belongs to deployment-level temporary-storage lifecycle management.

Operational logs contain job ID, file type, duration and error code only. They
must never contain filenames, worksheet names, cell values, formulas or macro
source.

## Issue #51 follow-ups

The upload-path crash, non-worksheet rejection, manifest privacy wording,
dimension-based cell-limit false positive and one-based sheet indexes are fixed.
The unused stale-workspace sweeper and its isolated test were removed; terminated
process cleanup is a deployment concern rather than an uncalled application hook.
