# Backlog

1. Verify the shared font catalogue against a live Google Workspace test tenant,
   compare representative before/after layouts, and add school-configurable aliases.
2. Harden the PPTX parser and mocked Google boundary tests; expand deterministic fixtures.
3. Fix the credential in the Publisher session's environment. It is NOT a permissions
   problem: that session signs in as Scrappy995, which already has write on this repo,
   and Codex pushes successfully as the same account. Read works, write returns 403,
   which means a restricted token rather than a restricted account. Check in that
   environment: `gh api repos/dfa-primarytech/workspace-migration-toolkit --jq .permissions`
   (push=false there proves it), and `env | grep -iE "GH_TOKEN|GITHUB_TOKEN"` — an
   injected read-only token silently overrides the stored credentials. Forking needs no
   token change and survives an environment that re-injects one.
4. Create the Google Cloud project: enable Drive, Slides, Docs and Sheets APIs, an Internal
   consent screen and a web OAuth client with redirect http://localhost:8080/auth/callback.
   Then validate a controlled real PPTX and a real DOCX end to end locally, before any
   Cloud Run deployment.
5. Enrich missing media where verified mapping is possible; report every unresolved item.
6. Collect PUB-002 onwards, and re-run PUB-001 locally after the layer
   classification change. The constructs libmspub really emits (groups as
   layers, rotated, flipped and cropped pictures, BorderArt, master content
   repeated per page) are now tested against its source, but not yet against a
   real file. Documents with each of those are the evidence most worth having.
7. Publisher → Google Slides renderer, only after that breadth exists
   (PROJECT.md section 38 stop point).
8. XLSX preflight and import.
9. Resolve DOCX fonts properly before wiring the shared substitution service.
   `docx.fonts()` reads literal `w:rFonts` values only, so a document using
   Word's **default theme fonts reports no fonts at all**, as does one whose
   fonts live in its styles. Requirements and measured evidence in
   `docs/font-substitution.md`. The mapping table itself is owned by the shared
   service, not by this stream.
10. Empty `<w:drawing>` residue left by every converted anchor (issue #20).
   Recorded only: no cleanup until a before/after rendering case shows an
   effect.
