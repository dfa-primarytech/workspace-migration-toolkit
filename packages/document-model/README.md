# document-model

The versioned intermediate representation shared by every source format.

`schema.json` is normative. `validation.py` enforces it, plus the
referential rules a JSON Schema cannot express: that every `assetId` on an
element resolves, that every asset use points back at a real element, and
that each page's element list matches the elements that claim the page.

Nothing here imports a third-party package, and nothing here touches a
Google API. Run the checks with:

```bash
python3 -m unittest discover -s tests/publisher -t tests/publisher
```

## Versioning

`schemaVersion` is `MAJOR.MINOR.PATCH`.

- **PATCH** — wording of a message, a new diagnostic code.
- **MINOR** — a new optional field. Existing consumers keep working.
- **MAJOR** — a field removed, renamed, or given a new meaning.

A consumer should accept any bundle whose major version it knows and
ignore fields it does not recognise.
