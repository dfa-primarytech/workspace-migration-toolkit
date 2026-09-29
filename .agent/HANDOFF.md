# Handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-text-fit`, based on main `43155f3` (#92 merged)
- Objective: fit substituted text inside its frame. PUB-001's live run showed Andika text running off pages 2 and 3, and under the frog on page 2.
- Files changed:
  - `publisher_fit.py` (new: layout with real font measurements; spacing, then size);
  - `publisher_slides.py` (`measured`, `text_requests(fitted=)`, sizes scaled to half points);
  - `font_metrics/andika.json` and its README (new: Andika's numbers only, no font file);
  - `scripts/font_metrics.py` (new: the extractor, run by hand with fontTools);
  - `pyproject.toml` (package data);
  - `tests/platform/test_publisher_fit.py` (new, 8 tests);
  - `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - Each text frame whose fonts have measurements is laid out before sending. If it overflows, line spacing is tightened (to no less than 1.2 em), then the size is reduced (to no less than 75%), and both are reported.
  - On PUB-001: page 2 gets 74% spacing and 90% size, page 3 gets 74% and 95%, and page 4's web address gets 74% and 90%.
- Checks:
  - Linux (host, app user, PUB-001 supplied): 469 passed, 11 skipped. The rebuilt image contains the metrics file.
  - Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - **Not yet seen on Google.** The layout is an estimate: Google's text insets are assumed. The next live run should confirm pages 2 and 3 now fit, and whether the 3% margin is right.
  - Still open from the live run: default table borders, and stretched pictures (the crop investigation).
- Decisions: DECISIONS.md, 2026-09-29 (fit substituted text).
- Next task: a live run to confirm the fit (the human mints a fresh one-hour token). Then the table borders, and the crop investigation.
- Warnings:
  - CT 203 still holds `/root/wmt-test/live`, containing the OAuth client secret and an expired picture token (root-only). The app container `wmt-test-live` is still running. Both stay only while live testing continues.
  - The image `wmt-test/app:pub4` has this branch's code.

---

## Previous handoff

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
