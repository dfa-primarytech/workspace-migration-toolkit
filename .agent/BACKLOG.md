# Backlog

1. Harden the PPTX parser and mocked Google boundary tests; expand deterministic fixtures.
2. Fix the credential in the Publisher session's environment. It is NOT a permissions
   problem: that session signs in as Scrappy995, which already has write on this repo,
   and Codex pushes successfully as the same account. Read works, write returns 403,
   which means a restricted token rather than a restricted account. Check in that
   environment: `gh api repos/dfa-primarytech/workspace-migration-toolkit --jq .permissions`
   (push=false there proves it), and `env | grep -iE "GH_TOKEN|GITHUB_TOKEN"` — an
   injected read-only token silently overrides the stored credentials. Forking needs no
   token change and survives an environment that re-injects one.
3. Create the Google Cloud project: enable Drive, Slides, Docs and Sheets APIs, an Internal
   consent screen and a web OAuth client with redirect http://localhost:8080/auth/callback.
   Then validate a controlled real PPTX and a real DOCX end to end locally, before any
   Cloud Run deployment.
4. Enrich missing media where verified mapping is possible; report every unresolved item.
5. Collect PUB-002 onwards. PUB-001 acceptance passes, but it is one clean
   document: it has no authored group, no `drawGraphicObject`, no master page,
   no metafile image, no embedded font, no list, no link and no rotation, so
   those adapter paths have synthetic tests only.
6. Publisher → Google Slides renderer, only after that breadth exists
   (PROJECT.md section 38 stop point).
7. XLSX preflight and import.
