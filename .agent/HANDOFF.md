# Handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-wordart`, based on main `58d1915` (#97 merged)
- Objective: recover WordArt. PUB-001's title "Early Reading at St.Vincent's" came through as two purple lines, as the human's screenshot from Publisher showed.
- Files changed:
  - `publisher_wordart.py` (new: read the WordArt properties, match to the outline layer, report unplaced);
  - `publisher_slides.py` (`_wordart`, `wordart_size`, outlines left out, the grouping pass skips WordArt);
  - `publisher_art.py` (`Prepared.wordart`) and `publisher.py` (reads it in the worker);
  - `tests/platform/test_publisher_wordart.py` (new, 4);
  - `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - On PUB-001 the title is a text box: "Early Reading" / "at St.Vincent's", Andika bold 31.5 pt, #8064a2, centred, where the WordArt was. No purple lines.
  - The human's Publisher screenshots of all four pages also confirmed all five crops.
- Checks:
  - Linux (host): platform and parser suites with the binary and PUB-001, 548 passed.
  - Ruff and mypy clean.
  - Not yet seen in Google: the picture token expired at 14:01 UTC.
- Known failures: none.
- Unresolved:
  - **Lists:** Publisher numbers PUB-001's table items and "Books to take home" (1., 2., 3.). libmspub never passes lists on, so the numbers are lost.
  - **Table borders:** the original table has black borders, so the no-borders default (#95) is wrong for PUB-001. Both are probably in the Contents stream; that needs investigating.
  - **Two sessions worked in this checkout at once.** The other session's uncommitted "join mid-sentence breaks" work is a local WIP commit, `7bf1f6c` on `feat/publisher-join-breaks`, awaiting the human's decision on joining breaks.
- Decisions: DECISIONS.md, 2026-09-29 (WordArt).
- Next task: a live run with a fresh token to see the title in Google; then lists and table borders.
- Warnings: CT 203's `/root/wmt-test/live` holds the OAuth client secret, the Picker key and an expired picture token. The container `wmt-test-live` and this machine's SSH tunnel on port 8080 are still up. The image `wmt-test/app:pub8` has this branch.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-text-wrap`, based on main `d44e17c` (#96 merged)
- Objective: keep text clear of pictures it wrapped around in Publisher. Slides has no text wrap (the human chose option 1: paragraph indents).
- Files changed:
  - `publisher_wrap.py` (new);
  - `publisher_slides.py` (`in_front_of`, `text_requests(extra=)`, `_indent`, notes);
  - `tests/platform/test_publisher_wrap.py` (new, 6);
  - `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - Paragraphs level with a picture in front are indented on its side, with an author's own indent kept.
  - The indents and the text fitting are repeated until stable.
  - A picture only counts if text is level with it (fixes a false note on page 4).
  - **Verified live on PUB-001:** pages 2 and 3 have no text under a picture. They drop to 11 pt to fit.
- Checks:
  - Linux (host): platform and parser suites, with the binary and PUB-001, 544 passed.
  - Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - The author's mid-sentence line breaks (page 3) now leave single words on a line more often. Joining those "soft" breaks is a possible follow-up, awaiting the human's call.
  - The whole paragraph moves: the page 2 heading "blending" wraps because it's level with the frog.
- Decisions: DECISIONS.md, 2026-09-29 (wrap with indents).
- Next task: merge on approval.
- Warnings: CT 203's `/root/wmt-test/live` holds the OAuth client secret, the Picker key and a picture token (expires 14:01 UTC). The container `wmt-test-live` runs `wmt-test/app:pub7`. Remove them when live testing ends.

---

## Previous handoff

- Agent: Claude Code / QuietHeron (Publisher)
- Date: 2026-09-29
- Branch: `feat/publisher-crops`, based on main `e36ddd6` (#95 merged)
- Objective: stop cropped Publisher pictures being stretched. The crop was in the file; libmspub dropped it.
- Files changed:
  - `native/pub-parser/src/main.cpp`, `model.h`, `collector.h`, `bundle.cpp` (write `drawing.bin`);
  - `tests/test_bundle.cpp` (new test);
  - `app/workspace_toolkit/publisher_crop.py` (new: read records, match, fit check);
  - `publisher_art.py` (`crop_picture`, `prepare(crops=)`);
  - `publisher_slides.py` (uses the cropped picture; "Cropped as in the original");
  - `publisher.py` (reads crops in the worker);
  - `tests/platform/test_publisher_crop.py` (new, 7);
  - `docs/publisher-parser.md`, `docs/publisher-renderer.md`, DECISIONS.md, this file.
- Completed:
  - The parser saves Publisher's drawing records.
  - The app recovers every picture's crop, matches it, checks it fits its frame, and cuts the picture before upload.
  - On PUB-001 all five cropped placements fit exactly, including the banner cropped two different ways on pages 1 and 4.
- Checks:
  - Linux (host): the image builds, with C++ tests 108/108. Platform and parser suites pass: 503, plus the parser's 59 with the binary and PUB-001 supplied.
  - Ruff and mypy clean.
- Known failures: none.
- Unresolved:
  - **Not yet seen in Google.** It needs a live run with a fresh picture token.
  - Outward crops (padding) aren't handled; they're left uncropped and reported.
- Decisions: DECISIONS.md, 2026-09-29 (picture crops).
- Next task: a live run to confirm the pictures on pages 1, 2 and 4, then merge.
- Warnings:
  - CT 203's `/root/wmt-test/live` holds the OAuth client secret, and a picture token that expired at 13:23 UTC. The container `wmt-test-live` is still running.
  - The image `wmt-test/app:pub6` has this branch.
