# Handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/PPTX)
- Date: 2026-10-21
- Branch: `feat/animation-video-prototype`, based on main `924cf4e`. Draft PR #196, not merged, not deployed, not wired into the hosted conversion.
- Objective: a deck's slide 6 is a 77-second narrated scene (96 effects over 55 pictures and groups, 8 motion paths, 12 sound cues). Slides cannot take animation and the API cannot create it. Keep it as a video beside the converted file, and put it on the slide.
- Files changed:
  - New `app/workspace_toolkit/animation_video.py`: reads one slide (shapes, groups with their own coordinate spaces, cropped/turned/flipped/outlined pictures, text boxes in a stand-in font) and its timing tree (absolute-time effects and sound cues, clip volume and trim); plays it with Pillow and encodes with ffmpeg. `select_slides`, `match_recordings`, and `attach` (saves the MP4 in the conversion folder, then puts a Drive video on the converted slide in place of its pictures). Commands: `python -m workspace_toolkit.animation_video render|select|attach`.
  - `pptx.py`: the check calls out a slide with 20 or more effects (`heavy_animation`) and says to record it as a video in PowerPoint beforehand.
  - New `docs/recording-animations.md`: the staff guide (which slides, how to record in PowerPoint, how to name the file `DECK - slide N.mp4`, where to put it, what the migration does, fixes).
  - New `tests/platform/test_animation_video.py` (55 tests, synthetic slides only).
- Completed:
  - Against PowerPoint's own MP4 of the same slide (made through PowerPoint's COM `CreateVideo` on the owner's PC): the same length, scene, positions and timing at 14 moments (mean pixel difference 2 to 10 out of 255) and sound level within about 0.1 dB.
  - Homelab, in a container limited to 2 CPUs and 2 GB as Cloud Run is: 45 s to make the 77 s video, 62 CPU-seconds, about 210 and 255 MB peak, a 5.4 MB MP4. Recording three times and uploading three times all worked.
  - Live, against real Google, on the owner's deck: `createVideo` with a Drive source is accepted, the slide's pictures are removed, and a video element (source DRIVE) is left. Done twice: with the player's video, and with PowerPoint's own recording named by the guide's rule.
  - A recording staff made is used as it is (named `DECK - slide N.mp4`, found by deck name exactly); a slide without one is played by the tool. A slide that cannot be recorded or placed costs only itself; a saved video that cannot be placed stays in the folder with the slide as it was. Failures name their reason in the log, not in the report.
- Checks: 921 platform tests pass (70 of them the animation and embedded-media tests); Ruff, format, mypy and the secret scan clean.
- Known failures: one live player run did not save a video and its cause was not seen (the next run, and three more recordings and uploads, were fine). Failures are logged with their reason now.
- Unresolved:
  - Playback in the Slides editor was not seen, only that Google accepted the request and the file is processed. The thumbnail API draws a grey placeholder for any private Drive video, PowerPoint's included, so it proves nothing. The owner is to open the two test decks and press play.
  - Drive takes a few minutes to process a new video (about 2.5 minutes in one measurement, longer for another); until then the slide shows a placeholder. The guide says so.
  - The video is private to its owner: whoever plays the deck needs access to it. The migration would need to share it (not done).
  - Not wired into the hosted conversion, and the hosted image has no ffmpeg (the test image added `imageio-ffmpeg`, about 60 MB). Whether it joins the hosted app or stays a tool for migrations we run is a decision; the staff-recording path needs no ffmpeg.
  - Not drawn or played: layout and master shapes, shape fills and lines, the exact font of text, theme colours for outlines, filters other than fade, wipe and wheel (played as a fade), animations of a shape inside a group.
- Embedded media (same branch): new `embedded_media.py`. `place_videos` puts each embedded video back on its slide from its saved Drive copy (a Drive `createVideo` where the still picture was; the still removed), and runs inside the hosted conversion (`google.convert`, after the online videos), needing no ffmpeg; it never stops a conversion. `place_sounds` wraps each visible sound in a short video (its own icon on a dark card, the audio at its trim) and puts that on the slide in place of the icon, because the Slides API cannot add a sound; it needs ffmpeg, so it is for the tool we run (`python -m workspace_toolkit.embedded_media sounds DECK PRESENTATION FOLDER`). `find_clips` lists them; a sound hidden off the slide is left alone. 15 new tests.
  - Live, through the app's real conversion code on a synthetic deck (a real embedded mp4 and a real embedded sound with a visible icon): the video was placed (`embeddedVideos: placed 1`), the sound wrapped, saved and placed, the slide holds two Drive videos, and Drive processed both (the wrapped sound 480x270 and 2.000 s, exactly its trim; the video 3.999 s). The owner's L2 deck has no embedded video file on a visible slide: slide 14's video is a YouTube link (handled by the online-video step) and its sounds are hidden off slide 6.
- Decisions: DECISIONS 2026-10-21.
- Next task: none claimed.
- Warnings:
  - The test deck is the owner's and shows people. It was only on the test host and in the scratch folder, and is deleted. Two converted test decks ("WMT animation test ... (delete me)") are left in the owner's Drive on purpose, for the owner to check playback, then delete.
  - A request Google refuses fails a whole batch, so a new request kind is tried against the live API first: this one was.
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
