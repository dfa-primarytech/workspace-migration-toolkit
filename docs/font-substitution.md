# What a font-substitution service needs from DOCX

An audit of how Word records fonts, what this converter currently reports, and
what has to change before DOCX can use a shared substitution service.

**This document deliberately contains no mapping table.** Which substitute to
pick for a given family is owned by the shared service, not by the DOCX stream.
The question here is only what DOCX must hand over so that service can decide.

## Why this matters for a trust

Staff documents lean on fonts the school installed and Google does not have —
Century Gothic in infant worksheets, Sassoon or Letter-Join in handwriting
practice, Wingdings for tick-box glyphs. A wrong substitution is not cosmetic:
a phonics worksheet set in a handwriting font becomes the wrong teaching
material, and a Wingdings tick that falls back to Latin becomes the letter `ü`.

## What the service must receive, per run

| Input | Where it lives in the package |
|---|---|
| Original family | `w:rFonts/@w:ascii`, `@w:hAnsi`, `@w:cs`, `@w:eastAsia` |
| ...or its theme reference | `@w:asciiTheme`, `@w:hAnsiTheme`, `@w:cstheme`, `@w:eastAsiaTheme` → `word/theme/theme1.xml`, `majorFont`/`minorFont` |
| ...or the style it inherits from | `word/styles.xml`: `docDefaults/rPrDefault/rPr/rFonts`, then the run's `w:rStyle`, then the paragraph's `w:pStyle`, walking `w:basedOn` |
| Style and weight | `w:b`, `w:bCs`, `w:i`, `w:iCs` — a family may substitute well at regular weight and badly at bold |
| Size | `w:sz`, `w:szCs` (half-points) — substitution changes metrics, and a heading that reflows to a second line is a visible break |
| Script and language | `w:lang/@w:val`, `@w:bidi`, `@w:eastAsia`; `w:rtl` |
| Whether the font is embedded | `word/fontTable.xml`: `w:embedRegular`, `w:embedBold`, `w:embedItalic`, `w:embedBoldItalic` |

Two of these are easy to overlook.

**Per-script fonts are not one choice.** A single run can name four families,
one per script range. Latin text uses `@ascii`/`@hAnsi`; Arabic and Hebrew use
`@cs`; CJK uses `@eastAsia`. Substituting the Latin family and applying it to
all four would render Arabic in a font with no Arabic coverage.

**An embedded font may need no substitution at all.** If `fontTable.xml`
embeds the family, the glyphs travel with the document. Whether Google's
importer honours embedded fonts is unverified — but the service should be told,
rather than substituting something already present.

## What this converter reports today

`docx.fonts()` collects literal `w:rFonts` attribute values and nothing else.
Measured against four fixtures:

| Document | Reported |
|---|---|
| Literal `rFonts` on the run | `['Comic Sans MS']` — correct |
| **Theme fonts (`w:asciiTheme="minorHAnsi"`)** | **`[]`** |
| **Font supplied only by the paragraph style** | **`[]`** |
| Per-script (`ascii` + `cs` + `eastAsia`) | `['Arabic Typesetting', 'Calibri', 'MS Mincho']` — all three, but flat |

The first two are the problem. **Theme fonts are what Word applies by
default**, so an ordinary document produced by clicking New and typing reports
*no fonts at all*. The preflight currently says such a document has nothing to
worry about, when in truth every glyph in it depends on a substitution nobody
has looked at.

The fourth is a lesser issue of shape rather than omission: the three families
are found, but flattened into one set, so nothing records that
`Arabic Typesetting` was serving complex script and `MS Mincho` CJK. A service
receiving that set cannot tell which substitution rules apply to which.

## Gaps to close before integration

1. **Resolve theme references.** Read `theme1.xml` and map `minorHAnsi`,
   `majorHAnsi`, `minorBidi`, `majorBidi`, `minorEastAsia`, `majorEastAsia` to
   real family names.
2. **Resolve style inheritance.** Walk `docDefaults` → `w:basedOn` chain →
   `w:pStyle`/`w:rStyle` → direct run formatting, with direct formatting
   winning. Without this, a document whose fonts live entirely in its styles —
   which is what a well-built template looks like — reports nothing.
3. **Keep the script dimension.** Report per-script rather than as a flat set.
4. **Report weights actually used**, not just families, so the service is not
   asked to guarantee a bold face nobody needs.
5. **Report embedded families separately**, since they may need no substitution.
6. **Cover `numbering.xml`.** Bullet glyphs carry their own `rFonts`, usually
   Symbol or Wingdings. A substituted bullet glyph turns a tick into a letter,
   and it is the kind of breakage staff notice immediately and cannot explain.

Items 1 and 2 are the ones that change the numbers; the rest change their
shape. None of them require deciding what to substitute.

## Interface this stream expects to call

Shape only — the shared service owns the real signature. What matters is that
the call is per distinct *requirement*, not per run, and that the answer can
say "no substitution needed".

```
substitute(
    family: str,                  # resolved, never a theme token
    script: "latin" | "complexScript" | "eastAsian" | "symbol",
    bold: bool, italic: bool,
    language: str | None,         # BCP-47, from w:lang
    embedded: bool,
) -> { family: str, exact: bool, note: str | None }
```

`exact=False` is what a conversion report should surface, per family, in the
same way equations and regenerated fields are surfaced now: state what changed
and let a person look, rather than claiming a fidelity nobody has verified.

## Not claimed here

Nothing in this document says what Google substitutes, or how well. Every
Google interaction in this repository is still a test double. The audit
describes what the *source* contains and what the service will need; measuring
what actually arrives requires a real conversion and human eyes.
