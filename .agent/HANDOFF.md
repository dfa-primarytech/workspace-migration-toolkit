# Handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/DOCX)
- Date: 2026-11-10
- Branch: `docx-flowchart-boxes`, based on main `b15b382`.
- Objective: a one-page Word flowchart (13 text boxes and arrows, anchored to paragraphs) converted to three pages with its boxes in the wrong order.
- Files changed: `docs.py` -- `_in_page_order` puts boxes anchored in one paragraph top to bottom, then left to right (they were in the order drawn); `_side_by_side`/`_replace_pair` keep two boxes that share a band of the page beside each other, as two cells of a borderless table, instead of stacking them. `test_docx_page_textbox.py` (5 new), `test_docx_sections.py` (one test's boxes moved apart so they do not pair).
- Checks: platform tests pass; Ruff, format, mypy clean.
- Unresolved: not yet confirmed in Google; the flow arrows are still floating shapes that Docs keeps unchanged (they no longer sit by their boxes); Word cannot open the converted file (empty drawing shells), so Word is no proxy here.
- Next task: none claimed.

---

## Previous handoff

- Agent: Claude Code (Claude Sonnet 5.5, platform/PPTX)
- Date: 2026-10-21
- Branch: `hosted-animation-video`, based on main `1fce024`.
- Objective: the hosted conversion records heavy animations and wraps sounds itself, so staff no longer need to run anything.
- Files changed:
  - `animation_video.py`: `hosted_enabled()` (on unless `WMT_HOSTED_ANIMATION=off`, and only where ffmpeg exists) and `record_hosted()` (the heaviest 3 slides, each at most 120 s of video, 240 s in all; slides beyond 3 are named in a warning; never raises).
  - `google.convert`: after the embedded videos, records animations (`report["animationVideos"]`) and wraps sounds (`report["soundVideos"]`, skipping slides given a video). Each step is non-fatal.
  - `pyproject.toml`, both lock files: `imageio-ffmpeg==0.6.0`, whose wheel carries a static ffmpeg (about 60 MB on the image).
  - Tests: `test_hosted_animation.py` (3), five more in `test_animation_video.py`; `conftest.py` switches recording off for every other test.
- Checks: 926 platform tests pass; Ruff, format, mypy clean.
- Unresolved: not yet run against live Google through the deployed service; the Docker build with ffmpeg not yet checked; the wrapped-sound and animation videos are private to their owner (viewers need access); the cost of recording lands on Cloud Run (about 45 s of 2 vCPU for a 77 s slide), kept bounded by the caps above. `WMT_HOSTED_ANIMATION=off` is the switch if the bill needs it.
- Next task: none claimed.

---

## Previous handoff

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
