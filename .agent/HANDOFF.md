# Handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/PPTX)
- Date: 2026-10-21
- Branch: `feat/animation-video-prototype`, based on main `924cf4e`. A prototype: a draft PR, not for merging as is, not deployed, not wired into the conversion.
- Objective: a deck's slide 6 is a 77-second narrated scene (96 effects over 55 pictures and groups, 8 motion paths, 12 sound cues). Slides cannot take animation and the API cannot create it. Can the tool record it as a video to sit beside the converted file?
- Files changed: new `app/workspace_toolkit/animation_video.py` (reads one slide: shapes, groups with their own coordinate spaces, cropped/turned/flipped/outlined pictures, text boxes in a stand-in font; reads the timing tree into absolute-time effects and sound cues; plays it with Pillow and encodes with ffmpeg; `python -m workspace_toolkit.animation_video DECK SLIDE OUT.mp4 [--png-at 5,20]`); new `tests/platform/test_animation_video.py` (33 tests, synthetic slides only).
- Completed:
  - Plays appear/disappear, fade, wipe, wheel, fly in (the `ppt_x` expressions, read by a small parser that never uses `eval`), motion paths (by length, with PowerPoint's speed-up/slow-down), grow/shrink, spin, transparency, clip volume and trim. Any other effect is counted in `notes`.
  - Compared with PowerPoint's own MP4 of the same slide (made through PowerPoint's COM `CreateVideo` on the owner's PC): the same length (76.75 s against 77.17 s with a half-second tail), the same scene, positions and timing at 14 moments (mean pixel difference 2 to 10 out of 255, mostly compression and a stand-in font), and sound level within about 0.1 dB in most 10-second windows.
  - Homelab, in a container limited to 2 CPUs and 2 GB, as Cloud Run is: 45 s to make the 77 s video, 63 CPU-seconds (python 40, ffmpeg 22), 210 MB and 254 MB peak, a 5.4 MB MP4. A still moment is drawn once (1,087 of 1,852 frames).
  - Found by comparison and fixed: picture outlines (two red boxes), and clip volume.
- Checks: 33 new tests pass with warnings as errors; Ruff, format, mypy and the secret scan clean. Each logic test was checked to fail when its behaviour is broken.
- Known failures: none. Not drawn or played: layout and master shapes, shape fills and lines (only text and pictures), the exact font of text (Dreaming Outloud Pro is a cloud font), theme colours for outlines, filters other than fade, wipe and wheel (played as a fade), animations of a shape inside a group, interactive triggers and repeat counts.
- Unresolved:
  - Nothing yet saves the MP4 to the conversion folder or puts it in the converted slide. Placing it would use the Slides `createVideo` request with a Drive source (not yet tried against the live API; the YouTube source was).
  - The hosted image has no ffmpeg. The prototype image added `imageio-ffmpeg` (about 60 MB). Whether to add it to the real image is a decision.
  - Cost on Cloud Run, by list price and the measured run: about 45 s of one 2 CPU, 2 GB instance, a fraction of a penny per animated slide.
- Decisions: none yet (DECISIONS 2026-10-21 records the prototype and what it did and did not prove).
- Next task: none claimed.
- Warnings:
  - The deck used to test is the owner's and shows people. It was on the test host and in the scratch folder only, and is deleted afterwards.
  - Windows on this PC blocks newly created virtual-environment python executables; tests were run on the base Python 3.14 with the packages on its path.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/PPTX)
- Date: 2026-10-20
- Branch: `feat/pptx-youtube-videos`, based on main `49ddb92`. Merged as #195 (`924cf4e`) and deployed to Cloud Run (revision 00008).
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
