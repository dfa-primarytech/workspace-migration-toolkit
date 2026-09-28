# Coding agent instructions

Read PROJECT.md, this file, CLAUDE.md and every file under .agent/ before working,
except HANDOFF-archive.md -- that's old session history already covered by git log
and merged PR descriptions; consult it only if you need history older than what
HANDOFF.md itself carries.
Inspect git status, branch, recent commits and existing tests before changing code.
Priorities: PPTX → Slides, DOCX → Docs, PUB → Slides, XLSX → Sheets.
Preserve the working Apps Script files under src/; platform work must not change them.
Do not commit real documents, extracted contents, credentials or tokens. Do not deploy
or create billable resources unless explicitly instructed. Never log document contents.
Work on a separate branch; do not overwrite another agent's uncommitted work.
Before finishing, run relevant checks and update .agent/CURRENT.md, HANDOFF.md and
BACKLOG.md. Append architectural decisions to DECISIONS.md; record superseding
entries rather than rewriting old decisions. Handoff must include agent, date,
branch/commit, objective, changed files, work completed, checks/results, known
failures, unresolved questions, decisions, next task and warnings.
