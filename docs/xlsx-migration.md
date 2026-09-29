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

VBA projects are read from the package only to calculate a content-free
inventory (count, byte length and digest). They are never executed, translated,
logged, placed in the conversion report or uploaded separately. Macro-enabled
workbooks containing VBA are archived to the customer's private Drive folder and
assigned `manual_migration_required`; they are not imported as a Google Sheet.
An `.xlsm` container without VBA or other blocking features can proceed to native
import if Google advertises that source MIME type for the account. An unsupported
source type returns a report retaining the archived original's link.

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

No Apps Script is generated in this MVP. Any later bounded script generation
must live behind a separate Google API interface, require explicit user or
administrator authorisation, store no generated source in reports, and have
mocked tests proving that lack of authorisation prevents creation. General VBA
transpilation is out of scope.

## Data lifecycle

1. The web request creates an isolated `wmt-*` temporary directory for one
   workbook.
2. The credential-free worker validates the package and writes a structural,
   temporary manifest. It serialises no cell values, formula expressions or
   VBA source.
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
