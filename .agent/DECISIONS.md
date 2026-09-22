# Architecture decisions (append-only)

## 2026-09-22: Priorities and isolation
PPTX → Slides first, then DOCX → Docs, PUB → Slides, XLSX → Sheets.
Preserve src/ unchanged. Publisher-first scheduling in historical research is
superseded by the user's priority update and platform continuation instruction.

## 2026-09-22: First shared application
Use a Python FastAPI application, separate from Apps Script, with a source manifest
boundary and native Drive PPTX import. No custom PowerPoint renderer. Use per-job
temporary directories, a subprocess parser and bounded ZIP/XML processing.
Use Google user OAuth with drive.file, encrypted short-lived HttpOnly cookies,
state + PKCE and CSRF checks. No service-account document ownership, refresh tokens,
central token store or public asset sharing. A stable encryption key works across
Cloud Run instances; jobs remain synchronous and bounded. No deployment in this task.
