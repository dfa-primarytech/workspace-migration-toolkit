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

## Testing

See [docs/platform.md](docs/platform.md#checks) for the full check suite
(`ruff`, `mypy`, `pytest`, `bandit`, `pip-audit`, the secret scanner). At
minimum:

```bash
pip install -r requirements-dev.lock
pip install --no-deps -e .
pytest -q
```

## Style

Match the surrounding code. Comments explain *why* a transform exists and what
breaks without it — that context is the hard-won part, so please preserve it.
