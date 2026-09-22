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

## Status

| Part | State |
|---|---|
| Callback adapter and IR model | Implemented, 83 unit tests passing |
| `publisher-parser` CLI | Implemented; failure paths tested end to end |
| Schema and validator | Implemented, 19 tests passing |
| Linux container | Written, **build not yet executed** — see [Verification gaps](#verification-gaps) |
| CI workflow | Written, **not yet executed** |
| PUB-001 regression | **Blocked** on the private fixture — see [PUB-001](#pub-001) |

The adapter has **not yet been run against any real `.pub` file.** Every
test to date drives it with synthetic callback sequences. That is a real
gap, not a formality: see [Verification gaps](#verification-gaps).

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

The sink links **only librevenge**, not libmspub. That is what lets every
unit test drive it with hand-built property lists — no `.pub` file, and no
real school document anywhere near the repository.

## Two findings that shape the model

**Publisher paints pictures as shapes with a bitmap fill.** The investigated
sample emitted *every visible image* as a `setStyle` with
`draw:fill = "bitmap"` followed by a rectangular `drawPolygon`, and never
called `drawGraphicObject` at all. A parser watching only
`drawGraphicObject` would report a school newsletter as having no pictures
in it. Both routes are supported, and every asset use records which one it
came through.

**`startLayer` is not a group.** librevenge emits layers as a rendering
construct. Treating one as a user-created Publisher group would invent
structure the author never made, so wrappers (`type: "wrapper"`,
`isAuthoredGroup: false`) and authored groups (`type: "group"`) are
different things in the model.

## Layout

| Path | Contents |
|---|---|
| `native/pub-parser/src/` | The C++ adapter and `publisher-parser` CLI |
| `native/pub-parser/tests/` | C++ unit tests driven by synthetic callbacks |
| `packages/document-model/` | Versioned IR JSON Schema + Python validator |
| `tests/publisher/` | Python tests: schema, CLI, PUB-001 harness |
| `tests/fixtures/publisher/` | Non-sensitive expectations only — never documents |
| `docker/publisher.Dockerfile` | Linux build/test image |
| `.github/workflows/publisher.yml` | Linux CI for the above |

## Dependencies

| Library | Tested version | Licence |
|---|---|---|
| [libmspub](https://github.com/LibreOffice/libmspub) | **0.1.4** (Ubuntu `0.1.4-3build7`) | MPL-2.0 |
| [librevenge](https://sourceforge.net/projects/libwpd/) | **0.0.5** (Ubuntu `0.0.5-3build1`) | MPL-2.0 / LGPL-2.1+ |

Both are installed from the distribution, not vendored. They are stable,
LibreOffice-maintained libraries with no reason to carry a private fork,
and vendoring would put a copy of someone else's MPL-2.0 source in this
repository for no technical gain.

`publisher-parser --version` reports the versions its binary was built
against, taken from `pkg-config` at configure time. Record that output
alongside any conversion result: the parser's behaviour is largely
libmspub's behaviour.

### Licence notices

This parser links libmspub and librevenge dynamically and does not modify
or redistribute their source. Both are available under the Mozilla Public
Licence 2.0; librevenge is additionally available under the LGPL 2.1 or
later. A distribution that ships the binaries (the container image does)
must carry their licence texts. The parser's own code is MIT, like the
rest of this repository.

The 1×1 PNG and the 41-byte JPEG in `native/pub-parser/tests/fixtures.h`
are byte arrays written for these tests. Nothing in this repository is
derived from a Publisher document.

## Building

```bash
sudo apt-get install -y build-essential cmake pkg-config libmspub-dev librevenge-dev
cd native/pub-parser
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
```

Three targets:

| Target | Links | Needs libmspub |
|---|---|---|
| `pubir` | librevenge | no |
| `publisher-parser` | `pubir`, libmspub, librevenge-stream | yes |
| `pubir-tests` | `pubir` | no |

## Running

```bash
publisher-parser input.pub output/
```

```text
output/
├── document.json
├── assets.json
├── report.json
└── assets/
    ├── <sha256>.png
    └── <sha256>.jpg
```

Exit codes: `0` complete, `1` libmspub could not parse the document,
`2` refused before or during output, `3` parsed but truncated by a
resource limit. **A non-zero exit still writes `report.json`**, so a caller
never has to interpret an exit code alone.

Useful options: `--force` (write into a non-empty directory),
`--max-input-bytes`, `--max-assets`, `--max-asset-bytes`, `--max-elements`,
`--max-seconds`, `--version`.

## Testing

```bash
# C++ adapter — synthetic callbacks, no .pub file, no network
native/pub-parser/build/pubir-tests

# Schema, validator and CLI
python3 -m unittest discover -s tests/publisher -t tests/publisher -v
```

Neither needs a Google API, credentials or a network. The Python tests
skip the CLI suite if the binary is not built, and skip the PUB-001 suite
if the private fixture is not supplied.

## PUB-001

`PUB-001` is a real four-page A5 school information booklet. **It is never
committed.** `.gitignore` refuses `*.pub`, CI fails if one appears under
`tests/fixtures/publisher/`, and a unit test asserts the same thing.

The repository holds only its SHA-256 and non-identifying structural
counts, in `tests/fixtures/publisher/PUB-001/expected.json`. Supply the
document from outside the repository:

```bash
export PUBLISHER_FIXTURE_PUB001=/path/outside/the/repo/PUB-001.pub
python3 -m unittest discover -s tests/publisher -t tests/publisher -v
```

Without it, those ten tests skip with an explicit reason. **A skip is not a
pass**, and the CI workflow's `pub001` job says so in its step summary
rather than going green in a way that could be mistaken for acceptance.

The expected counts came from an earlier investigation of the callback
stream, not from this parser. If the parser disagrees with them, that is a
finding to investigate — possibly a bug here, possibly a correction to the
expectations — not a number to quietly edit.

## Security

`.pub` files are untrusted binaries from a retired application.

- **Container validation is libmspub's**, through `isSupported`. Anything
  it refuses, the parser refuses.
- **Input size** is checked before libmspub sees the stream.
- **Resource limits** on callbacks, pages, elements, nesting depth, assets,
  asset bytes, text bytes, table cells, path commands and points. A limit
  *halts collection* rather than throwing: unwinding out of a callback
  through libmspub's own stack is not something it promises to survive.
  Callback counting continues past a halt, so the report's totals stay
  honest, and `truncation.truncated` says the bundle is partial.
- **Output filenames are generated** from payload hashes. Nothing from the
  document chooses a path.
- **No embedded content is executed** and **no network request is ever
  made** — not for a linked image, not for anything.
- **Operational output carries no document content.** Error messages are
  fixed strings chosen in the source. The bundle itself contains the
  document's text and images by design, and is written `0700`/`0600`.
- **Scratch files** are written under a `.tmp-<pid>` name and renamed into
  place, so an interrupted run never leaves a half-written `document.json`
  for a downstream job to read. Anything left by a failure is removed.

### The timeout is not complete

`--max-seconds` is enforced *inside the callback sink*. A hang inside
libmspub before it calls back would never reach it. **The invoking process
must impose its own hard subprocess timeout and kill the child.** The
Python harness does this (`PARSER_TIMEOUT_SECONDS`); any future service
integration must too.

## Compatibility statuses are candidates

Every element carries one of the shared statuses — `NATIVE`,
`SUBSTITUTED`, `FLATTENED`, `UNSUPPORTED`, `IGNORED` — alongside
`basis: "parser-candidate"` and a one-line `evidence` string.

At this stage these are **inferred from the callback stream**. Nothing has
been rendered into Google Slides and nothing has been compared. The
validator rejects a parser bundle that claims `basis: "verified"`.

## Verification gaps

Stated plainly, because the tests passing does not close them:

1. **No real `.pub` has been parsed.** Every passing test drives synthetic
   callbacks. The adapter's behaviour against libmspub's *actual* callback
   sequences — property spellings, ordering, which of the two image routes
   a given file uses — is inferred from the library's headers and an
   earlier investigation, not observed.
2. **The container image has not been built.** No Docker daemon was
   available. Package names and versions were verified on Ubuntu 24.04,
   which is why the image uses that base rather than Debian, but the build
   itself is unrun.
3. **CI has not executed.** The workflow is written but has never run.
4. **PUB-001 acceptance is blocked** on the private fixture.

Until (1) and (4) are done, the parser is a well-tested adapter of an
*assumed* callback stream. That is worth having, and it is not the same as
a working Publisher parser.

## Scope

Explicitly **not** in this milestone: Google Slides rendering, Google API
calls, OAuth, bulk migration, changes to the Apps Script DOCX fixer
(`src/`), and changes to the shared platform (`app/`, `tests/platform/`).
