# Font compatibility

Font substitution is a shared compatibility service. Source parsers report the
font family they found; they do not carry their own replacement tables.

The service has three outcomes:

- `AVAILABLE`: the family is in the reviewed Google Fonts candidate catalogue
  and is retained.
- `SUBSTITUTED`: a reviewed replacement exists. The original, replacement,
  confidence, reason and whether human review is required are reported.
- `UNKNOWN`: no replacement is guessed. The original is retained and the
  document is flagged for review.

`workspaceAvailability` remains `unverified` until the family is exercised in a
real Docs or Slides conversion. Membership in the Google Fonts catalogue does
not by itself prove availability in every Google Workspace tenant.

## Initial mappings

| Microsoft or third-party family | Google Fonts candidate | Confidence | Policy |
|---|---|---:|---|
| Calibri | Carlito | high | metric-compatible; apply |
| Cambria | Caladea | high | metric-compatible; apply |
| Arial | Arimo | high | metric-compatible; apply |
| Times New Roman | Tinos | high | metric-compatible; apply |
| Courier New | Cousine | high | metric-compatible; apply |
| Aptos | Carlito | medium | similar Office sans serif; apply and report |
| Comic Sans MS | Comic Neue | high | comic-style alternative; apply and report |
| Century Gothic | Montserrat | medium | geometric sans serif; apply and report |
| Sassoon Primary / Infant | Andika | medium | literacy-focused letterforms; apply and report |
| Bradley Hand / Segoe Print | Patrick Hand | medium | classroom handwriting; apply and report |
| Chalkboard / Chalkduster | Schoolbell | medium | school display handwriting; apply and report |
| OpenDyslexic / Dyslexie | Lexend | low | recommendation only; never auto-apply |

The complete table lives in `app/workspace_toolkit/fonts.py`, including common
serif, sans-serif, display and monospace Office families.

## PPTX behaviour

PPTX preflight annotates directly used and theme-declared fonts. During the
credential-free render step, reviewed candidates that do not require human
review are written into a copy of the package. The original upload is never
changed. The converted copy is sent to Google's native importer, and every
replacement and occurrence count is added to the conversion report.

Low-confidence accessibility mappings and unknown families remain unchanged.
This avoids replacing a deliberately chosen learner-accessibility font merely
because another family looks similar.

## Evidence and limitations

The Google Fonts repository is the catalogue source. Its `METADATA.pb` records
family, category, styles, weights and script subsets:
https://github.com/google/fonts and
https://github.com/googlefonts/googlefonts.github.io/blob/main/gf-guide/metadata.md

Carlito's project documents its Calibri metric compatibility:
https://github.com/googlefonts/carlito

The remaining visual and education-oriented mappings are curated policy, not
metric equivalence claims. They need representative-document review and later
live Google conversion evidence. Schools will eventually be able to add local
aliases for licensed or trust-specific fonts without changing parsers.

