# workspace-migration-toolkit

Tools for migrating Microsoft Office documents to Google Workspace without the
formatting falling apart.

Built during a UK multi-academy trust's M365 → Google Workspace migration.
The active tool is a Python/FastAPI app in
[`app/workspace_toolkit/`](app/workspace_toolkit/) — see
[docs/platform.md](docs/platform.md) for setup, configuration and branding.
It converts via native Google Drive/Slides import, with its own web UI,
browser sign-in and optional "Add from Drive" picker.

An earlier Google Apps Script version of the DOCX converter (`src/`) has been
removed from this repo. It's superseded by the platform app above, which
covers `.docx` and more without needing a separate Apps Script deployment per
site; its git history remains in this repo if the old approach is ever
useful as reference.

| Tool | Format | Status |
|---|---|---|
| [platform DOCX](docs/platform.md) | Word → Docs | **Working** (`app/workspace_toolkit/`) |
| [platform PPTX](docs/platform.md) | PowerPoint → Slides | **Working** (`app/workspace_toolkit/`) — [design](docs/research.md#powerpoint--google-slides) |
| xlsx estate analyser | Excel → Sheets | In progress — draft PR #72 |
| pub triage | Publisher → Slides/PDF | In progress — native parser merged, no Slides renderer yet — [⚠️ time-critical](docs/research.md#-time-critical-microsoft-publisher-retires-1-october-2026) |

---

## Getting started

See [docs/platform.md](docs/platform.md) for local setup, Google OAuth
configuration, Cloud Run deployment and branding.

## Roadmap

Excel and Publisher are still in progress on the platform app. See
[`docs/research.md`](docs/research.md) — including a **time-critical note on
Microsoft Publisher's retirement on 1 October 2026**.

## Contributing

Yes please — see [CONTRIBUTING.md](CONTRIBUTING.md). Sample files that convert
badly are as valuable as code.

## Licence

[MIT](LICENSE).
