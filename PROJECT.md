# Workspace Migration Toolkit — Project Specification

## 1. Project purpose

Workspace Migration Toolkit is an open-source, containerized toolkit for helping organisations migrate legacy Microsoft Office content to Google Workspace while preserving:

1. Content
2. Editability
3. Layout fidelity
4. Embedded assets
5. Transparency about anything that changed

The primary use case is education organisations migrating from Microsoft 365 / Microsoft Office to Google Workspace.

The application should eventually support:

| Source | Target |
|---|---|
| `.pptx` | Google Slides |
| `.docx` | Google Docs |
| `.pub` | Google Slides |
| `.xlsx` | Google Sheets |
| Embedded media | Google Drive |

The development priority order is:

1. **PowerPoint (`.pptx`) → Google Slides**
2. **Word (`.docx`) → Google Docs**
3. **Publisher (`.pub`) → editable Google Slides**
4. **Excel (`.xlsx`) → Google Sheets**

PowerPoint → Google Slides is the immediate priority. The Publisher-specific
milestones and scope below are retained for the third priority; they do not
block PowerPoint or DOCX work. This priority update supersedes earlier
Publisher-first sequencing. Planning and review precede implementation.

The current implementation milestone is the shared application foundation plus
PPTX preflight and native Google conversion. Agents must read `AGENTS.md`,
`CLAUDE.md` and `.agent/` before work, preserve `src/`, use temporary bounded
processing for untrusted files, and report detected content that cannot be
verified. Deployment and billable GCP resources require explicit instruction.

The existing working DOCX migration/fixer functionality in this repository must be preserved.

Do not refactor or break existing working functionality while developing the Publisher MVP.

---

# 2. Core product philosophy

The objective is NOT simply to make Microsoft files viewable.

The objective is to make legacy resources usable after migration to Google Workspace.

A teacher should be able to take a resource they previously edited in Publisher, PowerPoint, Word or Excel and continue editing it using Google Workspace.

The priority order is:

1. **Content preservation**
2. **Editability**
3. **Layout fidelity**
4. **Advanced visual effects**

For example:

A missing shadow is acceptable if reported.

A font substitution is acceptable if reported.

A slightly different unsupported graphical effect is acceptable if reported.

Turning an entire Publisher page into one giant PNG is NOT an acceptable default because the document is no longer meaningfully editable.

Silently losing text, images or other meaningful content is unacceptable.

---

# 3. Target user experience

The eventual product should be a simple self-service web application.

The intended user is a teacher or school employee, not a developer.

Typical flow:

```text
User signs in with Google
        ↓
Drops Microsoft Office file onto web app
        ↓
File analysed
        ↓
Compatibility summary
        ↓
User clicks Convert
        ↓
Document reconstructed/imported
        ↓
Output saved to Google Drive
        ↓
Open in Google Slides / Docs / Sheets
```

Example initial screen:

```text
┌────────────────────────────────────────────┐
│                                            │
│       Workspace Migration Toolkit          │
│                                            │
│   Drop your Microsoft Office file here     │
│                                            │
│          [ Choose a file ]                 │
│                                            │
│      PUB • PPTX • DOCX • XLSX              │
│                                            │
└────────────────────────────────────────────┘
```

Example analysis:

```text
RWI Information Booklet for parents 2024.pub

Analysing document...

✓ 12 pages detected
✓ 84 text elements
✓ 27 images
✓ 16 shapes
⚠ 4 fonts require substitution
⚠ 2 unsupported effects

[ Convert to Google Slides ]
```

Example result:

```text
Conversion complete

✓ 12/12 pages converted
✓ 84/84 text elements editable
✓ 27/27 images recovered
✓ 15/16 shapes recreated

3 changes were made during conversion.

[ Open in Google Slides ]

[ View conversion report ]
```

Do not expose technical terminology such as:

- XML
- librevenge
- EMU
- OOXML
- OAuth scopes
- parser internals

in the normal teacher-facing interface.

---

# 4. Architectural principle

Do NOT directly connect individual source parsers to Google APIs.

Use a common intermediate representation.

The architecture should eventually look like:

```text
                    INPUT FILE

       ┌────────┬────────┬────────┐
       │        │        │        │
      PUB      PPTX     DOCX     XLSX
       │        │        │        │
       ▼        ▼        ▼        ▼

              SOURCE PARSERS

                     │
                     ▼

        WORKSPACE INTERMEDIATE MODEL

                     │
          ┌──────────┼──────────┐
          │          │          │
          ▼          ▼          ▼

   Compatibility   Assets    Diagnostics
      Engine

                     │
                     ▼

              GOOGLE RENDERERS

          ┌──────────┼──────────┐
          ▼          ▼          ▼
       Slides       Docs      Sheets
```

Parsers understand Microsoft/source formats.

Renderers understand Google formats.

Parsers should not understand Google APIs.

Google renderers should not understand Publisher/PPTX internals.

The intermediate representation is the boundary between them.

---

# 5. Repository direction

This existing repository should evolve into the platform.

Do NOT create another repository.

A possible long-term structure is:

```text
workspace-migration-toolkit/
│
├── PROJECT.md
├── README.md
├── CONTRIBUTING.md
├── LICENSE
│
├── apps/
│   └── web/
│
├── packages/
│   │
│   ├── document-model/
│   │   ├── schema.json
│   │   ├── models.py
│   │   └── validation.py
│   │
│   ├── compatibility/
│   │   ├── fonts.py
│   │   ├── capabilities.py
│   │   └── warnings.py
│   │
│   ├── parsers/
│   │   ├── publisher/
│   │   ├── powerpoint/
│   │   ├── word/
│   │   └── excel/
│   │
│   └── renderers/
│       └── google/
│           ├── slides.py
│           ├── docs.py
│           ├── sheets.py
│           └── drive.py
│
├── native/
│   └── pub-parser/
│
├── tests/
│   ├── fixtures/
│   │   └── publisher/
│   ├── parser/
│   ├── renderer/
│   └── integration/
│
└── docs/
    ├── architecture.md
    ├── document-model.md
    └── compatibility.md
```

This structure is guidance, NOT a requirement to immediately reorganise the repository.

Do not perform a massive refactor simply to make the repository match this diagram.

Introduce structure incrementally.

---

# 6. Priority 3 — Microsoft Publisher

Publisher is the third development priority.

When Publisher work resumes, its target is:

```text
Microsoft Publisher
       .pub
        │
        ▼
     libmspub
        │
        ▼
 Publisher Adapter
        │
        ▼
Intermediate Representation
        │
        ▼
Google Slides Renderer
        │
        ▼
Editable Google Slides
```

---

# 7. libmspub

Use LibreOffice's open-source `libmspub` library.

Do NOT attempt to reverse-engineer the Microsoft Publisher binary format from scratch.

Investigate:

- libmspub
- librevenge
- `pub2raw`
- `pub2xhtml`

before deciding exactly how the adapter should work.

The preferred architecture is:

```text
original.pub
     │
     ▼
  libmspub
     │
     ▼
thin native adapter
     │
     ├───────────────┐
     ▼               ▼
document.json      assets/
```

The rest of the application should not need to know anything about Publisher's binary structure.

If necessary, create a small native C++ executable around libmspub/librevenge rather than creating extensive Python bindings.

For example:

```text
pub-parser original.pub output/
```

producing:

```text
output/
├── document.json
└── assets/
    ├── image_001.png
    ├── image_002.jpeg
    └── ...
```

Python/application code can then consume this output.

---

# 8. Intermediate document model

The intermediate representation must be:

- source-format independent
- versioned
- serialisable
- testable
- suitable for fixed-layout documents

Initial schema:

```json
{
  "schemaVersion": "1.0",
  "source": {
    "type": "publisher",
    "filename": "example.pub"
  },
  "document": {
    "title": "Example",
    "pageCount": 4
  },
  "pages": [
    {
      "id": "page_001",
      "width": 210,
      "height": 297,
      "unit": "mm",
      "elements": []
    }
  ]
}
```

---

# 9. Page elements

Every page element should have common properties where recoverable:

```json
{
  "id": "element_001",
  "type": "text",
  "bounds": {
    "x": 20,
    "y": 30,
    "width": 100,
    "height": 40
  },
  "rotation": 0,
  "zIndex": 3,
  "visibility": true
}
```

Initial supported element types:

```text
text
image
shape
line
table
group
unknown
```

Future types may include:

```text
video
audio
chart
```

Never silently discard an element simply because its type is unknown.

---

# 10. Text representation

Text must remain editable wherever possible.

Example:

```json
{
  "type": "text",
  "text": "Welcome to our school",
  "style": {
    "fontFamily": "Calibri",
    "fontSize": 18,
    "bold": true,
    "italic": false,
    "underline": false,
    "color": "#000000",
    "alignment": "center"
  }
}
```

Where possible, support:

- paragraphs
- runs
- mixed formatting
- font family
- font size
- bold
- italic
- underline
- text colour
- paragraph alignment
- line spacing
- character spacing
- language
- small caps
- superscript/subscript

Do not flatten text into images unless no reasonable editable representation exists.

---

# 11. Images

Images should be extracted as assets.

Example representation:

```json
{
  "id": "image_001",
  "type": "image",
  "assetId": "asset_001",
  "bounds": {
    "x": 30,
    "y": 75,
    "width": 60,
    "height": 45
  },
  "rotation": 0,
  "zIndex": 4
}
```

The binary image itself should live in:

```text
assets/
```

rather than being base64 encoded inside the main document JSON.

Preserve where possible:

- source format
- dimensions
- crop
- rotation
- transparency
- positioning
- z-order

---

# 12. Shapes

Basic Publisher shapes should map to the closest equivalent Google Slides shape.

Example:

```json
{
  "type": "shape",
  "shapeType": "rectangle",
  "fill": "#FFFFFF",
  "stroke": {
    "color": "#000000",
    "width": 1
  }
}
```

Advanced effects may initially be substituted or flattened.

Examples:

- shadows
- emboss
- engrave
- unusual WordArt
- unsupported gradients
- Publisher-specific effects

These must be reported.

---

# 13. Publisher page sizes

This is critical.

Do NOT convert Publisher files to 16:9 by default.

Publisher is frequently used for:

- worksheets
- newsletters
- certificates
- posters
- booklets
- leaflets
- parent information documents
- classroom displays

Preserve original physical page dimensions.

Example:

```text
Publisher

A4 portrait
210 × 297 mm

        ↓

Intermediate model

210 × 297 mm

        ↓

Google Slides

A4 portrait canvas
```

Likewise:

```text
297 × 210 mm

→ A4 landscape
```

Custom Publisher page sizes should be retained wherever technically possible.

---

# 14. Google Slides page-size technical spike

Do NOT assume that Google's Slides API can simply create arbitrary page dimensions.

Before implementing the renderer, verify exactly how custom page sizes can reliably be created.

Potential approaches may include:

- Slides API capability
- Google Drive API
- copying template presentations
- pre-created A4 portrait/landscape templates
- another supported mechanism

Document the result of this investigation before committing the renderer architecture.

---

# 15. Compatibility classification

Every source object should eventually be classified as one of:

## NATIVE

Can be recreated accurately as an editable Google object.

## SUBSTITUTED

Can remain editable but must be represented differently.

Example:

```text
Publisher font
     ↓
Google-compatible font
```

## FLATTENED

Visual appearance can be preserved, but editability is lost.

## UNSUPPORTED

Cannot currently be represented safely.

## IGNORED

Deliberately ignored by product policy.

Example:

```text
PowerPoint transition
```

---

# 16. Golden rule

Never silently destroy content.

This is a core engineering requirement.

Do NOT do:

```python
if not renderer.supports(element):
    continue
```

Instead:

```python
if not renderer.supports(element):
    report.add_warning(element)
```

If the parser detects something that cannot be represented, that fact must survive into the conversion report.

---

# 17. Font compatibility engine

Font substitution should exist in the compatibility layer.

Do not hard-code font substitutions inside individual parsers.

Conceptually:

```json
{
  "Calibri": {
    "replacement": "Arial",
    "confidence": "high"
  }
}
```

This example is illustrative only.

Do not blindly assume Arial is the best replacement.

The eventual mapping should consider font characteristics and Google availability.

Font status:

```text
AVAILABLE
SUBSTITUTED
UNKNOWN
```

Every substitution must be reported.

---

# 18. Google Slides renderer

The Google Slides renderer consumes:

```text
document.json
+
assets/
```

and produces:

```text
Google Presentation ID
+
Conversion Report
```

Responsibilities include:

- create or copy correctly sized presentation
- create pages
- preserve page ordering
- create text boxes
- insert text
- apply text styles
- create images
- create shapes
- create lines
- recreate tables where supported
- preserve element positioning
- preserve rotation
- preserve z-order where possible
- apply font substitutions
- record compatibility warnings

Use batch operations where appropriate.

---

# 19. Units and coordinates

Coordinate conversion must be centralised.

Do not scatter unit conversion mathematics throughout parser and renderer code.

Provide utilities such as:

```python
units.mm_to_points()
units.inches_to_points()
units.emu_to_points()
units.points_to_mm()
```

The intermediate representation should use predictable physical units.

---

# 20. Asset handling

Assets should have a separate manifest.

Example:

```json
{
  "asset_001": {
    "sourceName": "image1.png",
    "mimeType": "image/png",
    "sha256": "...",
    "status": "extracted"
  }
}
```

When Google integration occurs:

```json
{
  "asset_001": {
    "sourceName": "image1.png",
    "mimeType": "image/png",
    "sha256": "...",
    "driveFileId": "...",
    "status": "uploaded"
  }
}
```

This architecture will become particularly important when PowerPoint embedded video/audio support is added.

---

# 21. Google authentication

Use Google OAuth.

Expected flow:

```text
Teacher
   ↓
Google OAuth
   ↓
Workspace Migration Toolkit
   ↓
Teacher's Google Drive
```

Do not make a central service account the owner of everyone's teaching resources by default.

Request the minimum scopes necessary.

Credentials must be configuration/environment variables.

Never commit:

- client secrets
- access tokens
- refresh tokens
- service account credentials

---

# 22. Privacy architecture

This application will process school resources and may eventually encounter sensitive material.

Processing should be temporary.

Target lifecycle:

```text
upload
  ↓
temporary workspace
  ↓
analyse
  ↓
convert
  ↓
upload result to Google Drive
  ↓
DELETE source and temporary assets
```

The application should NOT become a permanent document repository.

Do not log:

- document text
- extracted images
- embedded media contents

Operational logs may include:

- job ID
- file type
- file size
- page count
- processing duration
- compatibility status
- errors

---

# 23. Conversion report

Every conversion should produce structured diagnostics.

Example:

```json
{
  "status": "completed_with_warnings",
  "pages": 12,
  "elements": {
    "total": 138,
    "native": 121,
    "substituted": 12,
    "flattened": 4,
    "unsupported": 1
  },
  "fonts": {
    "original": [
      "Calibri",
      "Comic Sans MS"
    ],
    "substituted": []
  },
  "warnings": []
}
```

The UI should translate this into plain language.

Example:

```text
Conversion completed

12 pages converted

121 elements preserved
12 elements changed slightly
4 graphical effects were flattened
1 item needs review

Pages needing review:

Page 7
```

Do NOT create a fake percentage such as:

```text
94% compatible
```

until enough empirical data exists to make such a metric meaningful.

---

# 24. Containerisation

The complete application should be containerized.

Development targets:

```text
Docker Desktop
Linux workstation
Homelab
```

Production target:

```text
Google Cloud Run
```

Application logic should remain cloud-agnostic.

Example environment variables:

```text
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI

MAX_UPLOAD_SIZE
TEMP_DIR
LOG_LEVEL
```

Do not hard-code organisation-specific configuration.

---

# 25. Priority 1 — PowerPoint architecture

Develop PowerPoint → Google Slides first, before new DOCX, Publisher and XLSX work.

Do NOT immediately attempt to rebuild the complete PowerPoint rendering engine.

Use a hybrid strategy:

```text
                       PPTX
                         │
                ┌────────┴────────┐
                ▼                 ▼

          Source analyser      Google import

                │                 │
                ▼                 ▼

          Source manifest    Google Slides

                │                 │
                └────────┬────────┘
                         ▼

                  Compare / Repair
                         │
                         ▼
                  Final Google Slides
                         │
                         ▼
                  Conversion Report
```

Let Google's converter handle constructs it already handles correctly.

Use our source analysis to detect and repair things Google loses or changes.

PowerPoint transitions and animations are intentionally low priority and may be ignored.

Embedded media is high priority.

Embedded video/audio should be extracted and preserved in Google Drive where possible.

---

# 26. Priority 2 — DOCX architecture

The repository already contains working DOCX migration/fixer functionality.

Preserve it.

Do not rewrite it simply to make it fit the new architecture.

Later, evaluate whether parts of the DOCX system should:

- remain standalone
- use the shared compatibility engine
- use the shared reporting engine
- integrate into the common web UI

Existing working behaviour takes priority over architectural purity.

---

# 27. Priority 4 — XLSX architecture

Excel should eventually use:

```text
XLSX
  ↓
Preflight analysis
  ↓
Google native conversion
  ↓
Inspect
  ↓
Repair
  ↓
Report
```

Potential future checks include:

- unsupported formulas
- macros
- VBA
- charts
- pivot tables
- external references
- named ranges
- conditional formatting
- unsupported Excel-specific constructs

This is NOT part of Publisher MVP.

---

# 28. Future bulk migration mode

Do NOT implement bulk migration during MVP.

However, do not make architectural choices that prevent it.

Future workflow:

```text
School document estate

14,284 Office files
        ↓

Preflight scanner
        ↓

┌──────────────────────────────┐
│ Safe automatic conversion    │
│ Conversion with warnings     │
│ Manual review                │
│ Unsupported                  │
└──────────────────────────────┘
```

This should eventually allow migration teams to assess Office compatibility before moving an organisation to Google Workspace.

The same conversion engine should power:

```text
single teacher upload
```

and eventually:

```text
large-scale migration assessment
```

---

# 29. Publisher MVP scope

Do not expand beyond this scope without explicit approval.

The Publisher MVP must:

1. Run locally.
2. Run in a container.
3. Accept one `.pub` file.
4. Parse it using libmspub.
5. Generate the intermediate JSON representation.
6. Extract images/assets.
7. Produce parser diagnostics.
8. Display/generate a basic analysis report.
9. Authenticate with Google.
10. Create an appropriately sized Google Slides presentation.
11. Reconstruct editable text boxes.
12. Reconstruct images.
13. Reconstruct basic shapes.
14. Reconstruct basic lines.
15. Preserve page ordering.
16. Preserve coordinates.
17. Preserve rotation where possible.
18. Preserve z-order where possible.
19. Apply basic font compatibility handling.
20. Generate conversion warnings.
21. Provide an Open in Google Slides link.
22. Delete temporary processing files.

---

# 30. Explicitly out of Publisher MVP

Do NOT implement:

- PPTX conversion
- XLSX conversion
- major new DOCX functionality
- bulk migration
- AI
- ML
- visual-difference AI
- admin dashboard
- PowerPoint animations
- PowerPoint transitions
- arbitrary migration orchestration

as part of the Publisher MVP. This boundary does not prevent separately prioritised PowerPoint or DOCX work.

---

# 31. Regression fixtures

Real school documents should form the core regression corpus.

The first Publisher fixture is:

```text
PUB-001
RWI Information Booklet for parents 2024.pub
```

Never modify source fixtures.

Suggested structure:

```text
tests/
└── fixtures/
    └── publisher/
        └── PUB-001/
            ├── original.pub
            └── expected-manifest.json
```

As additional real-world Publisher documents become available:

```text
PUB-002
PUB-003
PUB-004
...
```

Add them to the regression corpus.

These real files are extremely important because Publisher resources created by schools over many years will contain unusual constructs that synthetic tests may not represent.

---

# 32. Testing philosophy

Use both:

## Unit tests

For:

- model validation
- unit conversion
- font mapping
- compatibility classification
- asset handling

## Regression tests

For real Publisher documents.

Validate things such as:

```text
expected page count
expected page dimensions
text object count
image count
shape count
known text content
known fonts
asset extraction
element positions
```

## Integration tests

Eventually:

```text
PUB
 ↓
Parser
 ↓
IR
 ↓
Slides renderer
 ↓
Google Slides
```

Do not require Google API access for normal parser unit tests.

---

# 33. Definition of Publisher success

Success is NOT:

> Pixel-perfect Publisher emulation.

Success is:

> A teacher can open the converted Google Slides file and continue working on the resource without needing Microsoft Publisher.

Priority:

```text
Content
   ↓
Editability
   ↓
Layout
   ↓
Visual effects
```

Examples:

```text
Missing shadow
→ acceptable if reported
```

```text
Font substituted sensibly
→ acceptable if reported
```

```text
Complex unsupported graphic flattened
→ acceptable if reported
```

```text
Whole worksheet converted to PNG
→ unacceptable as default behaviour
```

```text
Text silently lost
→ unacceptable
```

---

# 34. Coding-agent operating instructions

These instructions apply to Codex, Claude Code and other coding agents working on this repository.

## Before writing code

Read this entire `PROJECT.md`.

Inspect the existing repository.

Understand the existing working functionality before changing architecture.

Do not perform unrelated cleanup.

Do not refactor working code merely because another structure looks cleaner.

---

# 35. FIRST PUBLISHER MILESTONE (DEFERRED)

Once Publisher work is prioritised, its first milestone is:

> **Publisher → Intermediate Representation**

NOT:

> Publisher → Google Slides

Do not begin the Google renderer until the parser boundary has been demonstrated and reviewed.

The first deliverable must demonstrate:

```text
PUB-001

RWI Information Booklet for parents 2024.pub

        ↓

      parser

        ↓

┌─────────────────────────┐
│ document.json           │
│ assets/                 │
│ diagnostics/report.json │
└─────────────────────────┘
```

---

# 36. First Publisher milestone tasks

1. Inspect the existing repository.

2. Document the relevant current architecture.

3. Investigate libmspub.

4. Investigate librevenge.

5. Investigate `pub2raw`.

6. Determine whether `pub2raw` exposes sufficient structure.

7. If not, implement the smallest practical native adapter around libmspub/librevenge.

8. Do NOT implement a new Publisher binary parser.

9. Add the versioned intermediate document model.

10. Parse PUB-001.

11. Extract assets.

12. Capture page dimensions.

13. Capture page ordering.

14. Capture element geometry.

15. Capture text content.

16. Capture text formatting where available.

17. Capture font information.

18. Capture images.

19. Capture basic shapes.

20. Capture z-order where recoverable.

21. Represent unknown elements.

22. Generate diagnostics.

23. Add automated regression tests.

24. Document parser limitations.

---

# 37. First Publisher milestone acceptance criteria

The milestone is complete when this command or equivalent:

```bash
publisher-parser \
  "RWI Information Booklet for parents 2024.pub" \
  ./output
```

produces:

```text
output/
├── document.json
├── report.json
└── assets/
```

and the output can be inspected without needing Microsoft Publisher or Google APIs.

The JSON should be sufficiently complete that another renderer could reconstruct the document without understanding the original `.pub` binary format.

---

# 38. PUBLISHER STOP POINT

After completing Publisher → Intermediate Representation:

**STOP.**

Do not immediately implement Google Slides rendering.

Present:

1. the resulting document model
2. extracted asset inventory
3. parser test results
4. unsupported Publisher constructs
5. libmspub limitations
6. proposed renderer mapping
7. any architectural changes recommended based on actual PUB-001 results

for review.

Only proceed to Google Slides rendering after approval.

---

# 39. Engineering principles

Throughout the project:

**Prefer boring, understandable engineering over cleverness.**

**Prefer deterministic conversion over AI guesses.**

**Prefer reporting a limitation over silently changing content.**

**Prefer real-world regression fixtures over synthetic assumptions.**

**Prefer incremental architecture over large rewrites.**

**Preserve working functionality.**

**Keep source parsers isolated from target renderers.**

**Keep the application portable and containerized.**

**Treat user documents as temporary data.**

**Never silently destroy content.**
