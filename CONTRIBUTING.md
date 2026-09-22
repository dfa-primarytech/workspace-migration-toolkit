# Contributing

This started as an internal tool for one trust's migration and works well enough
to be worth sharing. It is not polished. Contributions very welcome.

## Most useful contribution: broken samples

**A `.docx` that converts badly is worth more than a patch.** The transforms
were developed against four image-heavy primary-school worksheets. That is a
narrow sample, and the gaps are known:

- tracked changes, comments, footnotes
- complex numbering and cross-references
- long text documents rather than laid-out worksheets
- grouped shapes, SmartArt, charts, autoshapes with text

If you have a file that comes out wrong, open an issue describing what went
wrong. **Please don't attach anything containing personal data or anything your
organisation wouldn't want public** — a minimal reproduction built in Word is
ideal.

## Before writing transforms, probe the file

The single most useful habit from developing this: unzip a real sample and count
what's actually in it before assuming. Several passes were re-scoped after the
files turned out to contain something different from what was expected.

```bash
unzip -o sample.docx -d sample/
grep -o '<wp:anchor' sample/word/document.xml | wc -l
```

## Apps Script gotchas

These cost real time. Worth knowing before you touch `Code.gs`:

- **`XmlService.Element` has no `indexOf()`.** Use the `_contentIndex` /
  `_childIndex` helpers.
- **Element wrappers can't be compared with `===`.** Two reads of the same node
  return different JavaScript objects, so `indexOf` on an array of elements
  silently fails rather than throwing. Identity goes through the `_MARK`
  attribute helpers — see `_markKey`.
- **`Utilities.unzip()` rejects any blob not typed `application/zip`**, including
  a correctly-typed `.docx`. Retype a copy first.
- **File names are case-sensitive.** `createHtmlOutputFromFile('Index')` will not
  find `index.html`.
- **The manifest is `appsscript.json`** — two s's — and is edited in place via
  Project Settings, not added as a new file.

## Testing

Run the dependency-free regression tests with Node.js 20 or newer:

```bash
node --test tests/*.test.cjs
```

These execute the Apps Script and browser JavaScript with focused runtime stubs.
They cover unsupported-anchor preservation, upload guards and browser error
handling. They do not emulate XmlService or validate complete OOXML documents.
A full XML fixture suite remains valuable work (issue #2).

Before deploying, also convert known files in Apps Script and compare in Docs,
including charts, grouped shapes, canvases and the original worksheet layouts.

## Style

Match the surrounding code. Comments explain *why* a transform exists and what
breaks without it — that context is the hard-won part, so please preserve it.
