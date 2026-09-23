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
| Callback adapter and IR model | Implemented, 107 unit tests passing |
| `publisher-parser` CLI | Implemented; failure and limit paths tested end to end |
| Schema and validator | Implemented |
| PUB-001 regression | **Passing** against the real document — see [PUB-001](#pub-001) |
| Linux container | Written, **build not yet executed** — see [Verification gaps](#verification-gaps) |
| CI workflow | Written, **not yet executed** |

The adapter has been run against PUB-001, the real four-page A5 school
booklet, and reproduced every expected count: 4 pages at
420.944882 × 595.275591 pt, 22 elements, 82 paragraphs, 147 styled runs,
204 text insertions, 12 image placements over 11 deduplicated assets
(8 PNG, 3 JPEG, one reused across two pages), one 1×3 table, two paths,
one rendering wrapper and three fonts — **with zero diagnostics**, in
0.12 s.

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

**Publisher paints pictures as shapes with a bitmap fill.** Confirmed on
PUB-001: `drawGraphicObject` was called **zero** times, and all twelve
images arrived as a `setStyle` with `draw:fill = "bitmap"` followed by a
rectangular `drawPolygon`. A parser watching only `drawGraphicObject`
would report that school booklet as having no pictures in it. Both routes
are supported, and every asset use records which one it came through.

**A layer is sometimes a group, and the parser decides which.** libmspub
0.1.4 never calls `openGroup`. It emits an authored group as a layer with no
properties, and it also wraps a single shape painted in several passes
(border art, or any two of stroke, fill and text) in a layer, with
`svg:clip-path` when the shape is cropped. The parser classifies each layer
when it closes:

- a clip path means one cropped shape, so it stays a **wrapper**;
- a nested layer, or children placed apart rather than around one shape,
  means a **probable authored group**: `type: "group"`,
  `container.kind: "layer"`, and a `probable-authored-group` warning
  stating the evidence;
- anything else stays a **wrapper** (`isAuthoredGroup: false`).

The rule is conservative: a group whose largest child contains the others
stays a wrapper, losing the grouping but no content. This supersedes the
original "a layer is never a group" rule. See `.agent/DECISIONS.md`.

## What libmspub 0.1.4 actually emits

Checked against the library's own source (`MSPUBCollector.cpp`, `Fill.cpp`
at tag `libmspub-0.1.4`), and pinned by `tests/test_libmspub_shapes.cpp`:

| Construct | How it arrives | What the parser does |
|---|---|---|
| Picture | `setStyle` with a bitmap fill, then a shape | image, `bitmapFillShape` route |
| Rotated picture or shape | rotation folded into the outline; `librevenge:rotate` is emitted for **text frames only** | rotation recovered from a rotated rectangular outline (`rotation-from-outline`), instead of the picture being read as a mask |
| Flipped picture or shape | folded into the outline, which winds the other way | `outline-mirrored` warning. The bitmap itself is not mirrored |
| Fill rotated inside its shape | `librevenge:rotate` on the fill style, as a string | `fill-rotated` warning, value kept in the style properties |
| Cropped picture | a layer carrying `svg:clip-path` | wrapper with `layer-clip-path`. The clip is kept, not applied |
| Group | a layer with no properties | see above |
| BorderArt | the **only** use of `drawGraphicObject`: one call per tile | each tile flagged `probable-border-art` |
| Master page | never `startMasterPage`: the master's background and shapes are painted into **every page** before its own content | indistinguishable from page content; repeated on each page |
| Lists, links, fields | never emitted | not recoverable from a `.pub` through libmspub 0.1.4 |

The model still supports `openGroup`, master pages, lists, links and fields,
because it is meant to be source-independent. The tests driving those
callbacks are marked as not reachable from a `.pub`.

**libmspub declares column widths but not row heights.** PUB-001's table
carries a 386.897244 pt column and no `style:row-height` or
`style:min-row-height` on any of its three rows. Rather than leave a null
to be read as zero, the table records a `table-row-heights-unknown`
warning so a renderer knows the row geometry has to come from the
content.

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
`--max-input-bytes`, `--max-callbacks`, `--max-pages`, `--max-elements`,
`--max-assets`, `--max-asset-bytes`, `--max-total-asset-bytes`,
`--max-text-bytes`, `--max-seconds`, `--version`.

Each limit was exercised against PUB-001: every one halts collection,
reports `status: "truncated"` with the reason, exits `3`, and still emits
a bundle that passes full schema and referential validation.

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

With the fixture supplied: **107 C++ tests and 55 Python tests pass, none
skipped.**

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

The expected counts originally came from an earlier investigation of the
callback stream. **They have now been reproduced by this parser** against
the real document, and the file records several values that were measured
rather than predicted: the exact page geometry, the column width, the
per-font usage counts, the bold/italic run tallies, the font sizes and
colours, and the fact that `drawGraphicObject` is never called.

If the parser later disagrees with any of them, that is a finding to
investigate — possibly a bug here, possibly a libmspub change — not a
number to quietly edit.

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

1. ~~The container image has not been built.~~ Closed: it builds in CI and
   runs the C++ suite as part of the build.
2. ~~CI has not executed.~~ Closed: all checks run on every Publisher change.
3. **Only one real document has been parsed.** PUB-001 is a clean,
   modern, image-heavy A5 booklet. The constructs it lacks are now tested
   the way libmspub really emits them (see *What libmspub 0.1.4 actually
   emits*), but that is library source, not a real file. Grouped,
   rotated, flipped, cropped and border-art documents are the next real
   evidence needed. **PUB-002 onwards matter.**
4. **PUB-001 cannot run in CI**, because the document must not be
   committed. Acceptance is a local step until a private runner or a
   secured fixture store exists.

Closed since the first draft: the adapter has parsed a real `.pub`, PUB-001
acceptance passes, and the container build and CI run green. **PUB-001 must
be re-run locally** after the layer classification change. Its test asserts
its one layer is a wrapper.

## Scope

Explicitly **not** in this milestone: Google Slides rendering, Google API
calls, OAuth, bulk migration, changes to the Apps Script DOCX fixer
(`src/`), and changes to the shared platform (`app/`, `tests/platform/`).
