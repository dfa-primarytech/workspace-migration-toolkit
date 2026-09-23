# Shared platform and PPTX prototype

The legacy Apps Script DOCX application in `src/` is unchanged. The new Python
application lives in `app/workspace_toolkit/` and can be deployed independently.
No Publisher parser or custom PowerPoint renderer is included.

## What works

- Offline CLI preflight: actual presentation order, physical dimensions, text runs,
  direct text properties, declared fonts, masters/layouts/themes/notes inventory,
  tables/charts/shapes, relationships, assets and explicit risk warnings.
- Browser sign-in, analysis, conversion and report download. Native Google Drive
  import performs the rendering; Slides read-back checks count, dimensions and
  a whitespace-normalized text-token multiset per slide.
- Every extracted media/embedded payload is saved privately alongside the deck.
  Audio/video are not silently dropped if the native importer omits them.
- Per-operation temporary workspaces, bounded subprocess analysis, cleanup and
  generic user-facing errors. Explicit CLI output bundles are intentionally retained.
- Normal tests do not require Google credentials. API interactions are mocked.

The source manifest is an analysis model, not the full fixed-layout reconstruction
model proposed for the later Publisher parser. Renderers do not parse OOXML.

```text
browser / offline CLI
    → generated temporary source.pptx
    → bounded OOXML preflight subprocess
    → manifest + extracted assets + analysis report
    → user-authorized native Drive import (web conversion only)
    → private recovered assets in the same Drive folder
    → Slides read-back checks + conversion report
    → local job directory removed
```

## Local setup

Python 3.11+ is required; CI/container use Python 3.12. Runtime versions are pinned
in `requirements.lock`; development tools in `requirements-dev.lock`.

```bash
python -m venv .venv
# Activate .venv using your shell's normal command.
python -m pip install --upgrade pip
pip install -r requirements-dev.lock
pip install --no-deps -e .
workspace-preflight example.pptx ./job-output
workspace-server
```

The CLI refuses existing output directories. It writes `manifest.json`,
`report.json` and `assets/<sha256>`. Asset MIME type and original package names are
in the manifest; filenames on disk are generated hashes. Treat the entire bundle
as private document content. Do not commit it. There is no network access in the
preflight code. The CLI's explicit output is separate from automatically removed
scratch files.

Visit http://localhost:8080. The unauthenticated page and `/healthz` work without
credentials; analysis/conversion web routes require Google sign-in.

## Google configuration

Create a web OAuth client and enable the Drive and Slides APIs in your own project.
Register the exact redirect URI `PUBLIC_BASE_URL/auth/callback`. Configure:

- `PUBLIC_BASE_URL`: HTTPS origin in production; localhost HTTP is permitted locally.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`: OAuth application credentials.
- `SESSION_ENCRYPTION_KEY`: stable Fernet key shared by instances; generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- Optional `MAX_UPLOAD_SIZE` in bytes (default 25 MiB, configured maximum 100 MiB),
  `TEMP_DIR` (existing writable directory), `PORT`, `LOG_LEVEL`.

Environment values are read directly; `.env` is an example format, not automatically
loaded. Keep secrets outside Git. For Cloud Run, bind Secret Manager versions to
environment variables. Use a runtime service identity only for infrastructure
permissions; conversions use the signed-in user's OAuth token.

Only `drive.file` is requested. It supports file creation and Slides inspection
for files created by this application. Sessions use authenticated encryption in
short-lived HttpOnly/SameSite cookies. OAuth uses state and PKCE; mutations require
a session-bound CSRF token. No refresh token is requested or stored. Expired
sessions require sign-in again. Logging out clears the session cookie; it does
not revoke the user's Google grant. Rotating the encryption key invalidates all
sessions. There is no centrally persistent document or token database.

The UI analyses the chosen file first, then reuploads it for conversion. A source
hash prevents inadvertently converting a different file. This avoids retaining
server-side documents between user decisions. Assets and results remain private
in the user's Drive; no `anyone` permissions are added.

Official API references:
[Drive import](https://developers.google.com/workspace/drive/api/guides/manage-uploads),
[Slides get/scopes](https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations/get),
[OAuth web flow](https://developers.google.com/identity/protocols/oauth2/web-server).

## Container and Cloud Run

```bash
docker build -t workspace-toolkit .
docker run --rm -p 8080:8080 --env-file .env workspace-toolkit
```

The container runs as a non-root user and listens on `$PORT`. `/healthz` checks
process availability, not Google readiness. Cloud Run configuration is documented
in `deploy/cloud-run.example.yaml`; it is a template, not an automatic deployment.
Use a 300-second service request timeout, concurrency 2, and adequate memory for
both parser children and temporary files (the example uses 2 GiB). Application
jobs time out after 240 seconds; parser children after 30 seconds. The initial
version is synchronous, with no durable queue, cross-request job store or crash
recovery. A platform shutdown can interrupt a conversion.

No deployment or billable resource creation is authorized by this README.
Application access logs are disabled and operational events exclude filenames,
text and payloads. Before production, ensure infrastructure request logging does
not retain OAuth callback query strings or credentials.

## Input boundaries

Validate extension, transport MIME, ZIP signature and PowerPoint main content type.
Reject macros, encrypted/unsupported compression, unsafe/duplicate paths, dangling
internal relationships and unsafe XML. Default limits: 5,000 ZIP entries, 200 MiB
expanded package, 50 MiB per entry, 8 MiB per XML part, compression ratio 200:1,
and 500,000 elements per XML part, counted while it is parsed. For real
documents the 8 MiB part limit binds first: Word writes about 38 bytes per
element, so about 200 pages of text. The element limit only stops markup far
denser than an Office application writes. Linux workers also have CPU and 768 MiB
address-space limits. Windows workers enforce time and archive limits but have no
OS address-space cap. The subprocess inherits only a small runtime environment,
not configured OAuth credentials. These controls are not a general-purpose native
sandbox. Do not add external-resource fetching or executable/embedded-file execution.

Processing is always inside a temporary directory. Google writes cannot be made
transactional with local cleanup: failures can leave private partial outputs.
Reports expose known output/folder links. Do not blindly retry an uncertain
creation; inspect the folder first. An interrupted folder-creation response may
leave an output whose ID was never received. Infrastructure crash recovery and
idempotency across browser retries remain future work.

## What is not yet verified or implemented

- Live OAuth and actual Google PPTX conversion have not been exercised in this
  session; tests use mocked Google responses. No claim of visual fidelity.
- No automatic slide-object repair, media reinsertion, animation recreation,
  font substitution or OCR. Audio/video are preserved as separate Drive files;
  users can recover them, but playback in Slides is not guaranteed.
- `fonts` records directly referenced fonts outside theme definitions;
  `declaredFonts` records the theme's wider font inventory. Effective theme-font
  resolution and availability still require the compatibility layer.
- Effective font inheritance, layout transforms, SmartArt, embedded charts/OLE,
  unknown extensions and strict OOXML need further fixtures. Direct geometry is
  captured; group-relative coordinates retain their source transform.
- Unknown fonts remain `UNKNOWN`; a candidate `NATIVE` classification means
  eligible for Google's importer, not verified equivalence. The common statuses
  also include SUBSTITUTED, FLATTENED, UNSUPPORTED and IGNORED. Animations and
  transitions are detected and marked IGNORED; risky content is reported.
- Text comparison detects missing tokens, not reading order, styling, clipping or
  image/text identity. Every conversion retains a visual-review warning.
- Master/layout/theme inventories and text are retained, but the manifest is not
  a lossless reproduction of all XML features.
- No real private PPTX regression corpus supplied yet. Current fixtures are
  generated synthetic packages and must not be advertised as real-world fidelity tests.

## Checks

```bash
ruff check app tests/platform
ruff format --check app tests/platform
mypy app
pytest -q
bandit -r app -q
pip-audit --local --skip-editable
python scripts/check_secrets.py
node --check app/workspace_toolkit/static/app.js
```

GitHub Actions runs these checks plus a Linux Docker build and health smoke test.
It does not deploy. Keep `src/` untouched and compare it to the baseline when
working on the shared platform.
