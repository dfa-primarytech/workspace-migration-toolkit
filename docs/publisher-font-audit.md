# What the Publisher IR can tell the font-substitution service

An audit of the font evidence a `.pub` yields through libmspub 0.1.4, checked
against the shared service's contract (`app/workspace_toolkit/fonts.py`).
`docs/font-substitution.md` is the DOCX equivalent.

- Date: 2026-09-23
- Basis: `main` at `f3e71b2`, libmspub 0.1.4 source, PUB-001's measured
  output, and the shared service as merged
- Scope: evidence only. **No Publisher-only mapping** is proposed. Matching
  belongs to the shared service.

## Summary

1. **libmspub keeps font names and nothing else.** Its font table
   (`MSPUBCollector::m_fonts`) is a list of name bytes. It exposes no pitch,
   generic family, character set, PANOSE classification, weight class, width
   or Unicode coverage for any font. **For fonts that aren't embedded, the
   family name is the only matching evidence a `.pub` can supply.**
2. **Embedded fonts are the exception.** They arrive whole, as Embedded
   OpenType, and an EOT header carries the metadata a large-catalogue matcher
   wants. The parser records that a font is embedded but doesn't read the
   header. Reading it (metadata only, never the glyphs) is the one way to get
   richer evidence.
3. **Two findings against the shared service, both about PUB-001's own
   fonts.** They need to be fixed *together* (see *Against the shared API*):
   - Publisher's run-together names (`SassoonPrimaryInfant`) don't match the
     service's spaced keys (`sassoon primary`), so they fall through to
     UNKNOWN.
   - The Sassoon entries are MEDIUM confidence **without manual review**, so
     fixing the name match alone would switch on automatic replacement of a
     handwriting font.
4. **Symbol fonts can't be detected from metadata** in a `.pub` unless they're
   embedded. A content-based signal may exist but is unverified.
5. **Fixed in this PR:** embedded font sizes were over-reported by a third,
   and a font's definition was counted as a use.

## What PUB-001 gives the service today

| Family (as in the file) | Runs | Embedded | `compatibility()` today |
|---|---|---|---|
| SassoonPrimaryInfant | 138 | no | UNKNOWN, `no-reviewed-mapping`, manual review |
| SassoonPrimaryType | 8 | no | UNKNOWN, `no-reviewed-mapping`, manual review |
| Calibri | 1 | no | AVAILABLE, `measured-present-in-google-docs` |

146 of 147 runs use a handwriting family designed for early reading. A
converted booklet's appearance depends almost entirely on how the service
treats those two names.

## What a run carries

Every property libmspub 0.1.4 emits on a span, and where it lands in the IR.
Taken from `MSPUBCollector::getCharStyleProps` and the locale code beside it.

| Property | librevenge key | In the IR | Use for matching |
|---|---|---|---|
| Family | `style:font-name` | `run.fontFamily`, plus `document.fonts[]` | The lookup key. Decoded with libmspub's character-set guess, so a non-Latin name can arrive garbled |
| Size | `fo:font-size` | `run.fontSizePoints` | No |
| Bold | `fo:font-weight: bold` | `run.bold` | A style request, **not** a weight class: there's no 300, 500 or 600 |
| Italic | `fo:font-style: italic` | `run.italic` | Style request only |
| Small caps | `fo:font-variant` | raw style | No |
| All caps | `fo:text-transform` | raw style | No |
| Outline, shadow, emboss, engrave | `style:text-outline`, `fo:text-shadow`, `style:font-relief` | raw style | No: effects, not faces |
| Super- or subscript | `style:text-position` | raw style | No |
| Letter scaling | `fo:text-scale` | raw style | Hints at a condensed or expanded rendering. **Not** a width class |
| Language | `fo:language` (from the locale ID) | `run.language` | Yes, for script coverage |
| Country | `fo:country` | `run.country` | Weakly |
| Script | `fo:script` | raw style | Only when the locale names one explicitly, which is rare; **absent for en-GB**. Never inferred by the parser |
| Underline | `style:text-underline-*` | `run.underline` | No |
| Colour | `fo:color` | `run.color` | No |

"Raw style" means the property is kept verbatim in the run's `style` list, so
a consumer can read it, but the parser doesn't interpret it.

## What the document carries

`document.fonts[]` has one entry per family: `family`, `usageCount` (runs set
in it), `firstPageIndex`, `firstEventIndex`, `embedded`, `embeddedMime`
(always `application/vnd.ms-fontobject` from libmspub) and
`embeddedByteLength`.

## Matching metadata for a large catalogue

Each property the service asked for (pitch or generic family, weight, italic,
language or script, character set or signature, PANOSE, embedding), checked
one by one:

| Wanted | Non-embedded font | Embedded font |
|---|---|---|
| Pitch or generic family | **Absent** | In the EOT header's PANOSE bytes, **not read** |
| Weight | **Absent**: only a per-run bold flag | EOT `Weight`, **not read** |
| Italic | Per-run flag only (style, not face) | EOT `Italic`, **not read** |
| Language or script | Per-run `fo:language`; script rarely | Same, plus EOT Unicode and code-page ranges, **not read** |
| Character set or signature | **Absent** | EOT `Charset`, **not read** |
| PANOSE | **Absent** | EOT `FontPANOSE`, **not read** |
| Embedded | `embedded: true` plus MIME and size | Recorded |
| Embedding permissions | n/a | EOT `fsType`, **not read**. This is the licensing answer the parser defers to the renderer |

The EOT fields above are named from the format's published description (the
W3C member submission). **None has been read from a Publisher-embedded font
yet.** PUB-001 embeds none.

**Recommendation:** add an optional EOT header reader to the parser. It would
populate `document.fonts[].embeddedMetadata` with PANOSE, weight, italic,
character set, Unicode and code-page ranges, `fsType`, and the full and style
names. It would read the header only, never extract or write the glyph data,
and leave everything absent when the header is malformed. That's a schema
addition (minor version) and needs a real embedded-font `.pub` to test
against.

## Symbol and bullet fonts

The DOCX audit identifies symbol fonts by metadata: character set `02` and
PANOSE family kind 5 (Latin Pictorial). **A `.pub` supplies neither for a
font that isn't embedded.** For embedded ones, the EOT reader above would.

A possible content signal: text set in a symbol font is commonly encoded in
the U+F020–U+F0FF private-use range. If libmspub passes those code points
through, the share of a run's characters in that range would identify symbol
text without a list of names. **Whether libmspub 0.1.4 does that is
unverified.** Its text decoding goes through a character-set guess, and a real
file with Wingdings bullets is needed to find out.

Until then, the honest position is that Publisher can't detect the symbol
class. The service should keep such fonts UNKNOWN and unchanged, which it
already does for any name it doesn't recognise.

## Against the shared API

`compatibility(family)` takes a family name and nothing else. For
non-embedded Publisher fonts that loses nothing, because a name is all there
is. Two findings, both about the fonts PUB-001 actually uses.

**1. Publisher names don't match the service's keys.** `normalise_family`
collapses spaces and case, so it can't split a run-together name.
`SassoonPrimaryInfant` doesn't match `sassoon infant` or `sassoon primary`,
and `Sassoon Primary Infant` (spaced) matches neither key either. Publisher
commonly stores fonts under run-together or PostScript-style names, so this
will recur across the estate.

**2. Fixing (1) alone would switch on automatic substitution of a handwriting
font.** `sassoon primary` and `sassoon infant` map to Andika at MEDIUM
confidence **without** `manual_review`. The PPTX path applies any candidate
not marked for manual review, so once the names matched, Sassoon would be
replaced silently. Today only the name mismatch prevents that. DOCX avoids it
differently: #27 applies only high-confidence candidates, so Sassoon stays
Sassoon in a `.docx` while the same font becomes Andika in a `.pptx`. #27
records that as a known inconsistency, and notes that nothing in the catalogue
separates handwriting faces from ordinary display faces. Publisher shouldn't
add a third behaviour. The service owner should decide how handwriting and
early-reading families are treated, for example by marking them
`manual_review`, **before** name matching is widened.

Both belong to the shared service's owner. **Nothing in this PR changes
`fonts.py`.**

## What Publisher should hand the service

Evidence, not a mapping. One record per family, built from `document.fonts[]`
and the runs:

```json
{
  "family": "SassoonPrimaryInfant",
  "runs": 138,
  "boldRuns": 0,
  "italicRuns": 0,
  "languages": ["en"],
  "embedded": false,
  "embeddedMetadata": null
}
```

`embeddedMetadata` stays `null` until the EOT reader exists and succeeds.
Absent evidence is `null`, never a default. This lets the service move from
`compatibility(family)` to scoring on richer evidence without Publisher
guessing any of it.

## Fixed in this PR

- **`embeddedByteLength` was the base64 length.** The property reads back as
  base64 text, and its length was recorded as bytes, over-reporting by a
  third. It's now derived arithmetically from the base64 length, without
  decoding the font into memory.
- **A definition was counted as a use.** `defineEmbeddedFont` went through the
  run-counting path, so every embedded font reported one use too many, and one
  never used reported one. A definition now creates the entry with zero uses,
  and the first real use records its page.

Both are pinned by tests in `tests/test_libmspub_shapes.cpp`. PUB-001 embeds no
fonts, so its expected counts are unaffected.

## Not claimed here

- Nothing about which fonts a Google Workspace tenant has. That's the shared
  service's measured list.
- Nothing about Publisher-embedded EOT contents, which haven't been observed.
- That the private-use-range signal works for libmspub text. It's unverified.
