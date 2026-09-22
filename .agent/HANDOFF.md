# Handoff

- Agent: Codex
- Date: 2026-09-22
- Branch: `feat/platform-pptx-preflight`; implementation commits `3bf1f4a` and `a4ab50f`
- Base: `origin/main` at `730ecee`
- Objective: add the shared application foundation and first PPTX preflight/native-import workflow while preserving the Apps Script DOCX fixer.
- Files changed: coordination files; Python application under `app/`; platform tests; Docker/Cloud Run/CI configuration; dependency locks; `PROJECT.md`; `docs/platform.md`; `.gitignore`.
- Completed: bounded PPTX package inspection; text/font/asset/relationship/risk manifest; private extraction of embedded assets; Google OAuth state+PKCE flow; `drive.file` native import; private recovered-asset uploads; Slides count/size/text read-back checks; reports; temporary job cleanup; offline CLI; container and CI definitions.
- Checks: 37 Python tests passed; Ruff, formatting, mypy, Bandit, pip-audit, secret scan and JavaScript syntax passed. Existing DOCX tests passed 10/10 on merged main. Container build was not run locally because Docker is unavailable.
- Known failures: none in local checks.
- Unresolved: no live OAuth/Google conversion; no real PPTX regression fixture; no visual fidelity check; no automatic repair/media reinsertion; no durable queue/idempotency for interrupted Google writes.
- Decisions: FastAPI stays separate from Apps Script; native Drive import renders PPTX; preflight provides evidence and warnings; user OAuth uses `drive.file`; documents and tokens are not stored centrally. See `DECISIONS.md`.
- Next task: review the draft PR, then run one controlled real PPTX through preflight and a test Google account. Compare the original with converted Slides and add the resulting non-sensitive regression expectations.
- Warnings: do not edit this branch/worktree concurrently. Do not add credentials or real school documents to Git. A candidate `NATIVE` status is not verified compatibility. Google writes can leave private partial outputs after uncertain failures.
