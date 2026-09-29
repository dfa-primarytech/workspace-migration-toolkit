# Handoff

- Agent: Codex (XLSX)
- Date: 2026-09-29
- Branch: `rescue/xlsx-sheets-mvp`, merged with main `4c6d655`
- Objective: Fix issue #51: the `.xlsm` crash, chart-sheet rejection and conflicts with main.
- Files changed: XLSX pipeline modules and tests; shared package, pipeline, worker and web format registration; generated XLSX fixtures and documentation; coordination files. Main's Publisher/platform changes were retained by the merge. The pipeline-selection integration assertion in `tests/platform/test_docx.py` was updated only to recognise main's existing Publisher support.
- Completed: `.xlsm` keeps its source extension and MIME through native import; real VBA is reported as unsupported; chart sheets are retained and reported UNSUPPORTED; dialog and macro sheets require manual migration; generated fixtures cover both issue regressions; current main conflicts are resolved.
- Checks: 440 passed, 13 skipped; Ruff check passed; Ruff format checked 47 files; mypy passed 25 source files; Bandit passed; secret scan passed; JavaScript syntax passed.
- Known failures: none.
- Unresolved: live Google Sheets import remains unverified; cell-limit estimation, one-based sheet-index consistency and the unused sweeper remain follow-ups outside issue #51.
- Decisions: DECISIONS.md, 2026-09-28 (Excel source format and non-worksheet sheets).
- Next task: merge PR #72 after GitHub checks pass, then verify a synthetic workbook against a controlled Google Workspace tenant.
- Warnings: no real school files were used or committed. No GCP resources or credentials were created. Do not treat retained CLI manifests as content-free; they can contain sheet and external-workbook names.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-28
- Branch: `feat/publisher-convert`, based on main `4c6d655` (#91 merged)
- Objective: Publisher step 3 of 4. Convert a `.pub` to Google Slides: deliver pictures through a private bucket and signed links, send the plan, read it back.
- Files changed:
  - `storage.py` (new: keyless credentials, V4 link signing through IAM `signBlob`, upload and delete);
  - `publisher_convert.py` (new: create, move, build page by page, verify, report);
  - `publisher.py` (`render_path` plans in the worker; the step-1 convert stub is gone);
  - `publisher_slides.py` (plan save and load, the marked-box builder shared);
  - `worker.py` (plans `.pub` after parsing; a failure there doesn't stop checking);
  - `pipelines.py` (`ready`/`needs_settings`: `.pub` converts only where a bucket is set);
  - `web.py` (`describe(settings)`, settings passed to convert);
  - `google.py` (`save_report` and `failed` shared);
  - `config.py` (`PUBLISHER_BUCKET`, `PUBLISHER_SIGNER`);
  - tests `test_publisher_convert.py` (new, 15) and `test_publisher_app.py`;
  - `docs/publisher-storage.md` (new: the human's setup steps), `docs/platform.md`, `.env.example`, `deploy/cloud-run.example.yaml`, DECISIONS.md.
- Completed:
  - The full conversion path, tested against a fake Google that applies batches atomically and refuses unsigned or already-deleted pictures.
  - Signing matches Google's own V4 conformance cases, and a signed link verifies against a real RSA key.
  - The bucket is always emptied. The person's token never reaches the bucket, and the app's account never reaches Drive or Slides.
  - A picture Slides refuses becomes a marked box; the page is still built.
  - A lost reply is never sent twice.
  - A changed page size is reported.
  - `.env.example` no longer sets the old 25 MB `MAX_UPLOAD_SIZE`.
- Checks:
  - Windows: 433 passed, 13 skipped. Linux (host, app user, PUB-001 supplied): 436 passed, 10 skipped.
  - Ruff, mypy, bandit and the secret scan are clean.
  - **PUB-001 rehearsal** (real parser and worker in the app image, then the fake Google): worker 0.77 s; 4 slides with every object present and its text matching; 12 picture copies stored and all deleted; no signed link in the report.
- Known failures: none.
- **Step 4, live run with PUB-001 (2026-09-29): converted correctly.** The human ran the app image on the test host through an SSH tunnel from VM 210, signed in to a real staff account, with a one-hour token for `wmt-pictures` rather than any personal gcloud login.
  - The result: 4 A5 portrait slides; all 22 items read back on the right slides with their text; Sassoon shown as Andika; both rules as lines; the table; all 12 pictures, including a scannable QR code. The bucket was empty afterwards (0 objects).
  - The first two runs failed, and fixing them is in this PR:
    - `presentations.create` ignores `pageSize` (720 × 405 came back), so the presentation now comes from importing an empty A5 deck (`publisher_deck.py`);
    - the reader's `\r` paragraph marks, which Slides drops on insert, broke every text range. They are now stripped, `check()` refuses them, and the fake Google drops them.
  - Confirmed live: Slides fetches through signed links from a bucket with public access prevention; `batchUpdate` and Drive import work under `drive.file`; a service-account token signs its own links.
- Unresolved:
  - **Follow-ups seen on the slides:** Google's default table borders (the original had none); text flows a little differently (Andika metrics and Google's text insets), so the frog on page 2 overlaps two lines; four pictures stretched (crops lost upstream).
  - **Not yet exercised:** Cloud Run's own account, and a gcloud user login signing.
  - **To delete in Drive:** the two blank test presentations from the first two runs.
- Decisions: DECISIONS.md, 2026-09-28 (Publisher picture delivery) and 2026-09-29 (page size by import).
- Next task: merge #92 on the human's approval. Then decide on the follow-ups: borders, and line spacing for Andika.
- Warnings: the test host still holds `/root/wmt-test/private/pub-001.pub`, its bundle, `/root/wmt-test/repo`, `/root/wmt-test/live` (the OAuth client secret and the picture token, root-only) and the running container `wmt-test-live`. Stop the container and remove `live` as soon as testing ends; remove the rest when the Publisher work is finished.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-28
- Branch: `feat/publisher-renderer`, based on main `bb9cd61` (#90 merged)
- Objective: Publisher step 2 of 4. The renderer: IR → Google Slides API requests, offline.
- Files changed:
  - `app/workspace_toolkit/units.py` (new: lengths, frames, the Slides transform);
  - `publisher_art.py` (new: pictures Slides can take, drawn paths, composed border art);
  - `publisher_slides.py` (new: `plan`, `bind`, `check`);
  - `tests/platform/test_publisher_slides.py` (new, 38 tests);
  - `docs/publisher-renderer.md` (new), DECISIONS.md, this file, HANDOFF-archive.md.
- Completed:
  - Every IR element type has a mapping and a report line. See the table in `docs/publisher-renderer.md`.
  - Pictures carry a key until `bind()`; `keys_for(page)` lets step 3 sign links a page at a time.
  - `check()` refuses a plan Google would refuse: unknown requests, bad or duplicate IDs, use before creation, text ranges outside the text, unbound pictures.
- Checks:
  - Windows: 418 passed, 13 skipped. Linux (the human's Docker host, as the app user, with PUB-001 supplied): 421 passed, 10 skipped, including the PUB-001 plan test.
  - Ruff, mypy, bandit and the secret scan are clean.
  - **PUB-001:** 272 requests, no `check()` problems, pictures within 0.0001 pt of their frames. Status counts: 13 NATIVE, 7 SUBSTITUTED, 2 IGNORED. An offline drawing of the plan matched LibreOffice's rendering of the file.
- Known failures: none.
- Unresolved (all for step 3 or 4, and all unverified against Google):
  - whether `presentations.create` keeps an A5 page size (§14);
  - Google's text insets;
  - default table borders;
  - whether a 0.01 pt-tall line is accepted.
- Decisions: DECISIONS.md, 2026-09-28 (renderer defaults).
- Next task: step 3. Upload each page's pictures to the bucket, sign 15-minute links, `bind`, send, delete, then read the presentation back and report. The human creates the bucket and the signing permission; document the steps for them.
- Warnings:
  - Four PUB-001 pictures are heavily stretched. The reader drops Publisher's crops, and LibreOffice shows the same stretching. They are reported, not fixed.
  - The test host holds `/root/wmt-test/private/pub-001.pub` (the real booklet, mode 644 so the container user can read it) and its parsed bundle. Remove both when the Publisher work is finished.
