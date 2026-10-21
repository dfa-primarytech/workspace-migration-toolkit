# Recording an animated slide as a video, before a migration

Google Slides cannot play PowerPoint animations. A slide that is really a
timed scene (pictures arriving, leaving and moving across the slide, with
sound) loses all of that when it is converted, and its pictures end up piled
on top of one another. The fix is to record the slide as a video **in
PowerPoint, before the migration**. The migration then puts that video on the
slide in the converted deck.

This takes about five minutes a slide. You need the PowerPoint desktop app
(Windows or Mac). PowerPoint for the web cannot make a video.

## Which slides need it

Record a slide when it **plays by itself for more than a few seconds**, moves
things around, or has **sound**. Slides that only reveal a bullet or a picture
on each click do not need a recording.

How to spot them:

- In PowerPoint, open **Slide Sorter** (View > Slide Sorter). A small star
  under a slide means it has animation.
- Open the **Animation Pane** (Animations > Animation Pane) on a starred slide.
  A long list, or a list with sounds in it, means record it.
- The converter's **Check file** report lists animations by slide. A slide it
  calls out as a timed scene needs a recording.

## Recording a slide (Windows)

Do not change your original deck. Work on a copy.

1. Open the deck in PowerPoint.
2. **File > Save a Copy**, and give the copy a different name, such as
   `slide 6 recording`.
3. In the copy, delete every slide except the animated one. In the slide
   thumbnails, click the first slide you want to remove, hold **Shift**, click
   the last, and press **Delete**. Repeat for the slides on the other side.
4. Press **F5** to play it once, and check the animation and sound are what
   you expect.
5. **File > Export > Create a Video**.
6. Pick the quality. **HD (720p)** is plenty and keeps the file small; **Full HD
   (1080p)** if the slide has fine detail.
7. Leave **Use Recorded Timings and Narrations** switched on. Leave **Seconds
   spent on each slide** at 5: the video runs as long as the animation and
   sound do. If the video stops too early when you check it, raise this number
   to longer than the animation.
8. Click **Create Video**. In the Save box, set **Save as type** to **MPEG-4
   Video (\*.mp4)** and name the file exactly as shown below.
9. Wait for the progress bar at the bottom of the PowerPoint window to finish.
10. Play the MP4. Check that you can see the whole animation and hear the
    sound, and that it lasts as long as the animation does.
11. Close the copy without saving over anything, and delete it.

On a Mac: **File > Export**, choose **MP4** as the file format, pick the
quality, and **Export**. The rest is the same.

## Naming the file

Name each recording after the **original deck** and the **slide number**:

```
<deck file name without .pptx> - slide <number>.mp4
```

For a deck called `Lesson 2 - North America.pptx`, the recording of slide 6 is:

```
Lesson 2 - North America - slide 6.mp4
```

The deck name must match exactly, and the number is the slide's position in
the original deck. Recordings for other slides in the same deck are named the
same way, with their own numbers.

## Where to put it

Upload the MP4 to the **same Drive folder as the original deck**, next to it.
Do not rename or move the original. Leave the recordings there until the
migration has run.

## What the migration does with it

1. It converts the deck as normal.
2. For each recording it finds beside the deck, it saves the video in the
   conversion folder and puts it on that slide, **full slide, in place of the
   pictures that made up the scene**. Your original deck is not changed.
3. The report lists each slide it did this for.

People who play the converted deck need access to the video file in the
conversion folder. Share the folder with the same people as the deck.

Drive needs a few minutes to process a new video before it will play. Until it
has, the slide shows a grey placeholder with a cross. Give it five to ten
minutes after the migration, then open the slide and press play.

If there is no recording for an animated slide, it converts as before, with its
pictures piled together, and the report says so. A recording is always better
than the converter's own attempt.

## Videos and sounds that are already in your slides

Nothing for staff to do here.

- **A video file inside a slide** is saved in the conversion folder and put back on its
  slide, where its still picture was.
- **A sound** cannot be kept as a sound: Google Slides cannot hold one. The conversion
  wraps each in a short video (the speaker icon, with the audio) and puts that on the slide
  instead. Press it to play.
- **A YouTube video** is put back as a YouTube video. Other online videos (Vimeo,
  SharePoint, OneDrive) link from their still picture.
- A sound hidden off the slide, which played by itself, cannot be kept.

As with a recording, anyone who plays the deck needs access to these video files, and
Drive needs a few minutes before a new video plays.

## If something looks wrong

| What you see | What to do |
|---|---|
| The video stops before the animation finishes | Raise **Seconds spent on each slide**, or re-check that the copy kept only the one slide, and export again. |
| There is no sound | In the copy, check the sound icon on the slide is still there and its volume is on, then export again. |
| The video is very large | Export at HD (720p). |
| The animation needs clicks to move on | PowerPoint plays the steps by itself in the video; watch the MP4 to confirm it shows them all. |
| PowerPoint says it cannot create a video | Close other copies of the deck, save, and try again. |
| The migration did not use your recording | Check the name matches the deck exactly, and that it is in the same folder as the original. |

## For whoever runs the migration

The animation tool has three commands (`python -m workspace_toolkit.animation_video`):

- `select DECK.pptx` lists the slides that look like timed scenes.
- `render DECK.pptx SLIDE OUT.mp4` makes an approximate video itself, when no
  recording exists. It is close to PowerPoint's own but not exact: text is drawn
  in a stand-in font, and a few effects play as a fade.
- `attach DECK.pptx PRESENTATION_ID FOLDER_ID --recordings-dir DIR` saves the videos
  in the conversion folder and puts them on the converted slides. Recordings in
  `DIR` named as above are used as they are; any other selected slide is played
  by the tool. The Google token is read from `GOOGLE_ACCESS_TOKEN`.

The embedded-media tool (`python -m workspace_toolkit.embedded_media`, needs ffmpeg):

- `find DECK.pptx` lists the videos and sounds that show on slides.
- `sounds DECK.pptx PRESENTATION_ID FOLDER_ID [--skip 6]` wraps each sound in a video, saves it in
  the conversion folder and puts it on the converted slide. `--skip` leaves slides alone, such as
  a slide given to an animation video. Embedded videos need no step: the conversion does them.

## When the web converter does it for you

The hosted converter also records the heaviest animated slides itself (up to 3 per file, up to a minute each) and puts the video on the slide, so a recording made beforehand is only needed for exact results or for more than 3 slides. It names any slide it did not record in the report.
