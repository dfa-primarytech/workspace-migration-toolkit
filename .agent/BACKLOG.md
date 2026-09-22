# Backlog

1. Harden the PPTX parser and mocked Google boundary tests; expand deterministic fixtures.
2. Give the Publisher agent write access (collaborator or fork) — it cannot push, and
   #12 only exists because its work was rescued by git bundle.
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
