# Excel to Google Sheets migration

## MVP boundary

The Excel path uses Google Drive's native XLSX import for ordinary workbooks.
The worker first validates and inventories the OOXML package without network
credentials, then copies the package byte-for-byte to `converted.xlsx`. This
preserves formulas and workbook structures for the native importer rather than
attempting to reinterpret them in Python.

The implementation has not been tested against a live Google tenant. Offline
tests use a mocked Drive and Sheets API boundary. Read-back verifies worksheet
count, names, grid type and visibility only. Formula results, formatting,
charts, pivots, validation and protection still require review.

## Batch model and dependencies

A batch contains one `WorkbookJob` per workbook. Each job has an idempotency
key derived from its source digest, an attempt counter and explicit status.
Retry changes state but never silently repeats a Google create operation after
an uncertain response.

Preflight records external workbook target filenames only in the ephemeral
manifest. The batch planner matches those names to other files uploaded in the
same batch, detects cycles and can map resolved targets to destination Drive
IDs after their jobs finish. Conversion reports expose counts and findings,
not filenames, formulas or cell contents. This MVP does not rewrite Excel
external-link formulas: unresolved links and cycles require manual migration;
resolved links remain a review item until an authorised link-rewrite stage is
implemented and tested.

## Limits and escalation

Preflight enforces the package's compressed and expanded ZIP limits and checks
the Google Sheets limits of 10 million cells per spreadsheet, 18,278 columns
and 50,000 characters per cell. It inventories formulas by storage type,
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
workbooks are archived to the customer's private Drive folder and assigned
`manual_migration_required`; they are not imported as a Google Sheet.

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
   on success or failure. `sweep_stale_workspaces` is an explicit startup or
   scheduled hook for directories left by a terminated process.

Operational logs contain job ID, file type, duration and error code only. They
must never contain filenames, worksheet names, cell values, formulas or macro
source.
