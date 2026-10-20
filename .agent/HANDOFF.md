# Handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/PPTX)
- Date: 2026-10-20
- Branch: `feat/pptx-youtube-videos`, based on main `49ddb92`. Not merged, not deployed.
- Objective: an online video in a PowerPoint deck (the owner's "Insert Online Video" case) was lost in the conversion with no word. Map YouTube natively.
- Files changed: new `app/workspace_toolkit/online_video.py` (`classify` reads a video address: provider, YouTube id, start time; `apply` puts videos back after the import); `pptx.py` (`_online_video`: a `p:pic` whose `a:videoFile` link is an external video relationship gets `onlineVideo` and an `online_video` warning); `google.py` (`slides_batch`; `convert` calls `online_video.apply` after the checks and records `onlineVideos` in the report); new `tests/platform/test_online_video.py` (34 tests).
- Completed:
  - Before: only embedded video files were handled; an online video's link was skipped, and Google's import kept the still picture and dropped the link, with nothing reported.
  - Now: a YouTube video is added with the Slides `createVideo` request (source YOUTUBE) at the still picture's place and size, the picture removed, and a start time set from `start=` or `t=`. Other providers (Vimeo, SharePoint, OneDrive, SlideShare) cannot play in Slides, so the still picture gets the link (`updateImageProperties`). Each video is its own batch, so a refused one costs only that video, and a failure is reported, never raised.
  - Tested against the real Slides API on a synthetic deck (one YouTube, one Vimeo, one logo): `createVideo` accepted, the right picture replaced, the logo kept, the Vimeo picture linked. Then on the owner's own PowerPoint file: found, replaced, and Google drew the video's thumbnail in place. The test decks, folder and sign-in were deleted and revoked.
- Checks: 851 platform tests pass; Ruff, format, mypy and the secret scan clean.
- Known failures: none.
- Unresolved:
  - Only a YouTube address is mapped. A video embedded in the deck as a file is still saved to Drive with its still picture left. The same `createVideo` (source DRIVE) could embed that Drive copy; not tried (viewers would need access).
  - Animations are not touched: detected and reported as ignored. Ideas costed in the conversation: build-up slides for click-to-reveal effects; an internal PowerPoint-to-MP4 job.
- Decisions: DECISIONS 2026-10-20.
- Next task: none claimed.
- Warnings:
  - This Windows PC blocks newly created virtual-environment `python.exe` files. Tests were run on the base Python 3.14 with a temporary `.pth` in its site-packages (the worker subprocess needs it); remove `wmt-dev-temp.pth` there.
  - A request Google refuses fails a whole batch, so a new request kind is tried against the live API first: this one was.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/Publisher)
- Date: 2026-10-06
- Branch: `fix/publisher-empty-table-cells`, based on main `c6689e2`. Merged as #194 (`49ddb92`) and deployed to Cloud Run (revision 00007).
- Objective: the school's 28-page Publisher booklet came out of Slides with tables running over each other and off the page.
- Files changed: `publisher_slides.py` (`_blank_cell_style`, `_blank_cell`; `deleteText` added to `KNOWN` and to `check`), new `tests/platform/test_publisher_table_cells.py`.
- Completed:
  - Cause: 30 of 45 cells in one table were empty tick boxes. Publisher stores no font for an empty cell; Slides sets an unstyled one in 18 pt, so every row was about 31 pt tall, not the planned 20.5 pt, and a table planned at 307 pt came out near 450 pt.
  - Fix: an empty cell is given the font and size most of its table's text uses (scaled as the text is), by putting a space in, styling it and deleting it.
  - Tested against the real Slides API: styling an empty cell directly is refused ("The object has no text"), so that route was dropped before shipping. With the space in and out, rows render about 23 pt. Page 19 of the booklet was replayed, old plan against new, onto scratch decks (290 requests accepted): the table's rows are visibly shorter. The scratch decks and the temporary sign-in are gone.
- Checks: 817 platform tests pass; Ruff, format, mypy and the secret scan clean.
- Known failures: none.
- Unresolved:
  - Only page 19 was replayed. Pages 20, 21 and 5 (overlapping tables, a table running off the page) should improve for the same reason; they need a real conversion to confirm.
  - Text still made 75% smaller on 11 tables (pages 5, 9, 19, 20, 21, 24, 27) and may overflow; not touched.
  - Tables' borders are Publisher's default grid (the file stores none).
- Decisions: none new.
- Next task: none claimed.
- Warnings: the booklet is the owner's file; it lived on the test host only while testing and was removed. A request Google refuses fails a whole page, so any new request kind is tried against the live API first.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/Publisher)
- Date: 2026-10-06
- Branch: `feat/publisher-wmf-pictures`, based on main `77c46c3` (#192, deployed to Cloud Run that day). Not merged.
- Objective: a school's 28-page Publisher booklet converted to Slides badly. Its clipart was missing.
- Files changed: new `app/workspace_toolkit/metafile.py` (a bounded WMF renderer: filled polygons, polypolygons with holes, rectangles, ellipses, solid brushes, plain pens; refuses a metafile needing text, a bitmap or an arc); `publisher_art.py` (`_open` draws a WMF); new `tests/platform/test_metafile.py` (metafiles built in code).
- Completed:
  - The booklet's six WMF pictures (pages 16 and 17) were `UNSUPPORTED: picture-missing`; they now convert (0 unsupported). Drawn and looked at: clipart illustrations, correct way up. A negative window extent (Publisher's own) was the bug the first run found; there is a test for it.
  - Run through the container with this branch: 28 pages, status counts NATIVE 130, SUBSTITUTED 155, IGNORED 96, FLATTENED 2.
- Checks: 814 platform tests pass; Ruff, format, mypy and the secret scan clean.
- Known failures: none in the code. Not checked in Google.
- Unresolved, all on the same booklet and all unseen in Slides:
  - 29 tables over 12 pages. 11 had their text made 75% smaller and may still overflow (pages 5, 9, 19, 20, 21, 24, 27); 21 narrow columns were widened (pages 10, 12, 16, 17, 19 to 21, 24). Borders are Publisher's default grid, as the file stores none.
  - 74 shapes are drawn as separate lines.
  - What the teacher meant by "a lot of pages to redo" needs the converted deck or screenshots next to the original.
- Decisions: none new.
- Next task: none claimed.
- Warnings: the booklet is the owner's file, kept on the test host only and removed afterwards; never put its contents in issues, PRs or tests. The test image `wmt-test/app:wmf` on the test host is from this branch; `wmt-test/app:main` is main `77c46c3`.
