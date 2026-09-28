# Shared platform and PPTX prototype

The earlier Apps Script DOCX application has been removed from this repo; DOCX
now converts through this same platform. The Python application lives in
`app/workspace_toolkit/` and can be deployed independently. No Publisher
parser or custom PowerPoint renderer is included.

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
- Optional `MAX_UPLOAD_SIZE` in bytes. **Unset by default: there is no upload
  limit** (issue #36), and the page shows none. Set it only if a deployment
  needs a cap. Also optional: `TEMP_DIR` (existing writable directory), `PORT`,
  `LOG_LEVEL`.
- Optional `PUBLISHER_BUCKET` and `PUBLISHER_SIGNER`: turn on Publisher
  conversion. Set up as in `docs/publisher-storage.md`.
- Optional `GOOGLE_PICKER_API_KEY`: a Cloud Console API key, restricted to the
  Google Picker API, with the Picker API enabled. Adds an "Add from Drive"
  option beside the local file chooser. Unlike the OAuth client secret, this
  key is designed to be used from browser JavaScript -- the API restriction is
  what keeps it safe to expose, not secrecy. Left unset, the feature is hidden
  and the app behaves exactly as before.

  **Verified live against a real GCP project (2026-09-28)**, both analyse and
  convert, for a Drive-picked `.docx` and `.pptx`. Two things the reasoned
  design got wrong, found only by testing for real:
  - A Website (HTTP referrer) restriction on the API key breaks Picker --
    Picker's own file-list requests aren't made from this page's origin, so
    referrer checking rejects them. Restrict the key to the Google Picker API
    only, not by website.
  - A `drive.file`-scoped app's per-file grant on a picked file did not
    reliably take effect without also calling `setAppId()` on the
    `PickerBuilder`, with the OAuth client's own Cloud project number (the
    numeric prefix of the client ID). Implemented in app.js; see
    `Settings.picker_app_id`.
  - The Content-Security-Policy needed `style-src 'unsafe-inline'` too:
    gapi's picker widget sets inline `style="..."` attributes directly on
    elements it creates in this page, not only inside its iframe. There is no
    hash/nonce to apply to markup a third party generates.

  `documents.get` and `files.export` (PDF) were also confirmed reachable
  under `drive.file` scope on a file this app created -- see issue #53.

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

## Branding

The frontend (`app/workspace_toolkit/static/`) ships branded with PrimaryTech's
own design system out of the box: `brand.css` holds the design tokens (colors,
type scale, spacing, radii, shadows) as CSS custom properties, `style.css`
consumes those tokens rather than hardcoded values, and `primarytech-logo.svg`
is the wordmark referenced from `index.html`.

To re-brand for another deployment:

- Replace the `:root { ... }` token values in `brand.css` with the target
  brand's own colors/type/spacing -- `style.css` picks up the change
  automatically since it never hardcodes a value itself. Component rules
  should not need to change unless the new brand's layout genuinely differs.
- Swap `primarytech-logo.svg` for the new logo (or update the `src`/`alt` on
  `#brand-logo` in `index.html` if the replacement has a different filename).
- If the new brand's typeface isn't system/Google-Fonts-hosted the same way,
  update the `@import` at the top of `brand.css` and the CSP's `style-src`/
  `font-src` additions in `web.py` (`create_app`'s `safe_errors` middleware)
  to match the new font host, or drop them if self-hosting fonts instead.
- No other file depends on brand-specific values; `app.js` and the Python
  backend are brand-agnostic.

## Container and Cloud Run

```bash
docker build -t workspace-toolkit .
docker run --rm -p 8080:8080 --env-file .env workspace-toolkit
```

The container runs as a non-root user and listens on `$PORT`. `/healthz` checks
process availability, not Google readiness. Cloud Run configuration is documented
in `deploy/cloud-run.example.yaml`; it is a template, not an automatic deployment.
Deploy to `europe-west2` (London): the app stores nothing itself, so this region
is the entire data-residency surface it controls, and the frontend states it
directly for DPO review ahead of converting sensitive material. Where the
converted file ends up living is Google Drive storage, governed by the
organisation's own Workspace data-location policy, not by this app.
Use a 3600-second service request timeout (Cloud Run's maximum, as the
example sets), concurrency 2, and adequate memory for both parser children and
temporary files (the example uses 2 GiB).

The request timeout must stay above the app's own deadlines, which grow with
the file (`config.py`):

- **The job** (`job_timeout_for`): 240 seconds, plus one second for every
  512 KiB of the file, capped at `job_timeout_ceiling` (3300 seconds). The cap
  sits under the 3600-second request timeout, so the app stops a job and
  reports it itself, rather than Cloud Run cutting the request off with no
  report. A file picked from Drive is timed again once its real size is known.
- **The parser child** (`parser_timeout_for`): 30 seconds, plus one second for
  every 4 MiB, doubled when pictures are being made smaller. It runs inside the
  job, so the job's deadline still bounds it.

A shorter request timeout (such as the 300 seconds this page once gave) would
end large conversions before the app's own deadline, with no report. The initial
version is synchronous, with no durable queue, cross-request job store or crash
recovery. A platform shutdown can interrupt a conversion.

No deployment or billable resource creation is authorized by this README.
Application access logs are disabled and operational events exclude filenames,
text and payloads. Before production, ensure infrastructure request logging does
not retain OAuth callback query strings or credentials.

## Input boundaries

Validate extension, transport MIME, ZIP signature and PowerPoint main content type.
Reject macros, encrypted/unsupported compression, unsafe/duplicate paths, internal
relationships that escape the package, and unsafe XML. A relationship to a part
that is simply absent is reported (`relationship_target_missing`), not fatal,
unless it is a slide; part names resolve case-insensitively. Default limits: 5,000 ZIP entries, 8 MiB
per XML part, compression ratio 200:1, and 500,000 elements per XML part,
counted while it is parsed. For real documents the 8 MiB part limit binds
first: Word writes about 38 bytes per element, so about 200 pages of text. The
element limit only stops markup far denser than an Office application writes.

The zip-bomb guards scale with the file rather than being fixed: one part may
expand to 2x the file and the whole package to 3x, never less than 50 MiB and
200 MiB. Real media barely compresses, so a real file of any size stays inside
them, while a small crafted file still meets the floor. The analysis time
allowance is 30 s plus 1 s per 4 MiB, and the job allowance 240 s plus 1 s per
512 KiB, capped at 3,300 s, under Cloud Run's 60-minute request limit. Linux
workers also have a CPU limit from the same allowance, and an address-space
limit of 768 MiB plus twice the file. Windows workers enforce time and archive
limits but have no OS address-space cap.

**Measured memory (issue #36)**: about 75 MiB plus 4x the file per job at peak,
most of it the job folder, which on Cloud Run is RAM. Two 94 MiB jobs at once
peaked at 751 MiB. **Size limits that remain are Google's**: its published
conversion limits are 50 MB to Docs and 100 MB to Slides or Sheets. A larger
file is warned about (`beyond_import_limit`) before converting, not refused. If
Google then turns it down (its upload, or a call on the converted file,
fails), the reason given for the failure (`stoppedBecause`) names that limit
in plain words instead of a generic upload failure.
**Embedded video is taken out before a deck goes to Google** (issue #36): Slides
does not import embedded video (`docs/research.md`), and the conversion saves
each video to the conversion folder anyway. The video's part, its relationships
and the markup that plays it are removed; the picture element stays, so the
slide shows the video's poster frame where the video was. Audio is left alone.
A video also used as a picture, or in a part whose edit cannot be confirmed by
re-parsing, is kept. Its relationships and content-type override are removed whether written
as empty or paired tags, and under any prefix, and each edit is read back to
confirm it (`package.py`: #124, #136, #137); a shape's size tag (`a:ext`) is
never taken for an empty extension. The report lists what was removed (`videosRemoved`), warns
`videos_removed`, and warns `removed_video_not_saved` if a removed video's Drive
copy failed -- its original file then still has it. The import-limit warning
judges the file Google receives, not the upload.
Saved copies are named `<deck> – slide NN – <name>`, where `<name>` is the
object's own name when PowerPoint gave it a meaningful one (it names an
inserted video or sound after its file) and `video 1`, `audio 2` and so on
otherwise. PowerPoint's defaults such as "Picture 3" count as no name.
**Publisher `.pub` files can be checked, and converted to Google Slides where
a picture bucket is set up** (DECISIONS.md, 2026-09-28). The app image builds `native/pub-parser` in a Debian stage (its
C++ tests run during the build) and ships it as `/usr/local/bin/publisher-parser`;
elsewhere set `PUBLISHER_PARSER_BIN`. The worker runs it with a hard timeout --
its own `--max-seconds` cannot stop a hang inside libmspub -- and limits scaled
with the file, and `publisher.analysis_report` summarises the bundle. The same
worker then draws the pictures and plans the Slides requests
(`publisher.render_path`, docs/publisher-renderer.md); `publisher_convert` sends
them, handing pictures to Slides through `PUBLISHER_BUCKET`
(docs/publisher-storage.md). Without a bucket, a conversion is refused before
the upload (`not_convertible`, 501) and the page offers only Check.

**"Make pictures smaller" is opt-in** (issue #36, step 3): a checkbox beside
Convert, off by default, sent as `X-Compress-Pictures: 1` and honoured only on
`/api/convert` -- checking a file never changes it. The worker then rewrites the
converted copy (`pictures.py`); the person's own file is untouched. Each picture
in a plain picture frame is reduced to the size it is drawn at, at 220 ppi
(PowerPoint's Compress Pictures default), allowing for its crop, and a photo
stored as PNG is re-saved as JPEG (the part is renamed and its relationships and
content types follow, in whatever prefix the file uses; if its content types
can't be edited and confirmed, no picture is changed). Left alone: pictures under 100 KB, formats other than PNG
and JPEG, JPEGs with an EXIF rotation, CMYK, pictures with transparency or few
colours (diagrams, screenshots, text), pictures used anywhere but a picture
frame or inside a group, anything over 60 megapixels (refused undecoded), and
any result not at least 10% smaller. The report lists every change
(`pictures`) and warns `pictures_compressed`; a failure is never fatal
(`pictures_not_compressed`, and the pictures go at full size). Uses Pillow.
The server is Hypercorn, which speaks HTTP/2 without TLS: Cloud Run refuses an
HTTP/1 request body over 32 MiB, so deploy with end-to-end HTTP/2 (the `h2c`
port name in `deploy/cloud-run.example.yaml`). The subprocess inherits only a small runtime environment,
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
It does not deploy.
