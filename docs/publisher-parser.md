# Publisher parser → intermediate representation

Milestone 1 of the Publisher workstream: read a Microsoft Publisher `.pub`
file and emit a versioned, source-independent intermediate representation
(IR) plus extracted assets and parser diagnostics.

**This milestone stops at the IR.** No Google Slides rendering, no Google
APIs, no OAuth. See [Scope](#scope).

```text
input.pub → libmspub → native adapter → document.json
                                      → assets.json
                                      → report.json
                                      → assets/<sha256>.<ext>
```

## Why a native adapter

`libmspub` is the only open-source reader for the Publisher binary format,
and it is a C++ library that drives a `librevenge::RVNGDrawingInterface`
callback sink. Two alternatives were rejected:

- **Writing a new `.pub` binary parser.** The format is undocumented and
  the effort is unbounded. `libmspub` already exists and is the code
  LibreOffice ships.
- **Parsing `pub2raw` text output.** `pub2raw` prints the same callback
  stream in an ad-hoc, human-oriented text format with no stability
  guarantee, and it discards binary payloads. It is a useful *debugging*
  tool for understanding what a file contains; it is not a data interface.

So the adapter implements `RVNGDrawingInterface` directly and builds the IR
in the callback sink. Nothing downstream needs to know anything about
Publisher's binary structure.

## Layout

| Path | Contents |
|---|---|
| `native/pub-parser/src/` | The C++ adapter and `publisher-parser` CLI |
| `native/pub-parser/tests/` | C++ unit tests driven by synthetic callbacks |
| `packages/document-model/` | Versioned IR JSON Schema + Python validator |
| `tests/publisher/` | Python tests: schema, golden IR, fixture harness |
| `tests/fixtures/publisher/` | Non-sensitive expectations only — never documents |
| `docker/publisher.Dockerfile` | Linux build/test image |
| `.github/workflows/publisher.yml` | Linux CI for the above |

## Plan

1. Define the versioned IR schema.
2. Implement the smallest direct callback adapter around
   `MSPUBDocument::isSupported` / `MSPUBDocument::parse`.
3. Unit-test the adapter with synthetic callback sequences.
4. Add the CLI and its output bundle.
5. Add the Linux container build and CI.
6. Run against available controlled fixtures.
7. Run against PUB-001 if and when the private fixture is supplied.

## Scope

Explicitly **not** in this milestone: Google Slides rendering, Google API
calls, OAuth, bulk migration, changes to the Apps Script DOCX fixer, and
changes to the shared platform under `app/`.
