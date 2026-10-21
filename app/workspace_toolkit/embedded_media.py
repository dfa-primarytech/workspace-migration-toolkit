"""Embedded video and sound in a PowerPoint deck, put back into the converted deck.

Google's import drops both. A video is already saved in Drive beside the deck
(the conversion does that), so it is put back with a Drive video element where
its still picture was, as the animation videos are. The Slides API has no way to
add a sound to a slide, so a sound is wrapped in a short video (a card with its
icon, and the audio) and that video is put there instead: a click on it plays
the sound, as a click on the speaker icon did. Wrapping needs ffmpeg, so it is
for the tool we run ourselves, not the hosted app.

What is left alone: a sound or video hidden off the slide (background sound that
played by itself, which a slide cannot do), and a slide given to an animation
video, whose pictures are replaced by the recording.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import subprocess  # nosec B404 -- fixed argv, no shell, ffmpeg only
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .animation_video import (
    EMU_PER_PT,
    MAX_MEDIA_BYTES,
    _ffmpeg,
    _pt,
    read_scene,
    slide_parts,
)
from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning
from .online_video import _still

logger = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".wmv", ".avi", ".mpg", ".mpeg", ".webm", ".mkv", ".3gp"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".wma", ".aac", ".ogg", ".oga", ".flac"}
# The video a sound is wrapped in must be big enough to find and press.
MIN_SOUND_WIDTH_PT = 160.0


@dataclass
class Clip:
    """One picture on a slide that plays an embedded video or sound."""

    slide: int  # 1-based
    id: str
    part: str  # the media part it plays
    kind: str  # video or audio
    box: tuple[float, float, float, float]  # x, y, width, height, in points
    trim: tuple[float, float] | None  # start and end of the part played, ms
    poster: str | None  # the picture it shows


def find_clips(deck: Path) -> list[Clip]:
    """Every video and sound that shows on a slide, with its place."""
    clips: list[Clip] = []
    with zipfile.ZipFile(deck) as archive:
        for number, part in enumerate(slide_parts(archive), start=1):
            scene = read_scene(archive, part, load_media=False)
            width, height = scene.width_emu / EMU_PER_PT, scene.height_emu / EMU_PER_PT
            for node in scene.nodes:
                if node.kind != "pic" or not node.audio:
                    continue
                suffix = Path(node.audio).suffix.lower()
                kind = (
                    "video"
                    if suffix in VIDEO_SUFFIXES
                    else "audio"
                    if suffix in AUDIO_SUFFIXES
                    else None
                )
                box = (
                    node.x / EMU_PER_PT,
                    node.y / EMU_PER_PT,
                    node.w / EMU_PER_PT,
                    node.h / EMU_PER_PT,
                )
                # Off the slide is a sound that plays by itself; there is nothing to click.
                if (
                    kind is None
                    or box[0] + box[2] <= 0
                    or box[1] + box[3] <= 0
                    or box[0] >= width
                    or box[1] >= height
                ):
                    continue
                clips.append(Clip(number, node.id, node.audio, kind, box, node.trim, node.blip))
    return clips


def saved_by_part(manifest: dict, report: dict) -> dict[str, str]:
    """The Drive copy of each media part the conversion saved, by the part's name."""
    found: dict[str, str] = {}
    for output in report.get("assetOutputs", []):
        asset = manifest.get("assets", {}).get(output.get("assetId", ""))
        for part in (asset or {}).get("sourceParts", []):
            found[part] = output["driveFileId"]
    return found


def _create_video(
    slide: dict, name: str, drive_id: str, box: tuple[float, float, float, float]
) -> dict:
    return {
        "createVideo": {
            "objectId": name,
            "elementProperties": {
                "pageObjectId": slide["objectId"],
                "size": {
                    "width": {"magnitude": box[2], "unit": "PT"},
                    "height": {"magnitude": box[3], "unit": "PT"},
                },
                "transform": {
                    "scaleX": 1,
                    "scaleY": 1,
                    "translateX": box[0],
                    "translateY": box[1],
                    "unit": "PT",
                },
            },
            "source": "DRIVE",
            "id": drive_id,
        }
    }


def _wanted(box: tuple[float, float, float, float]) -> dict:
    return {"x": box[0], "y": box[1], "width": box[2], "height": box[3]}


def _plural(count: int, what: str) -> str:
    return f"{count} {what}{'' if count == 1 else 's'}"


def _log(event: str, slide: int, error: BaseException) -> None:
    logger.warning(
        json.dumps(
            {
                "event": event,
                "slide": slide,
                "error": type(error).__name__,
                "code": getattr(error, "code", ""),
                "reason": str(getattr(error, "detail", None) or error)[:300],
            }
        )
    )


async def place_videos(
    google: Any,
    presentation_id: str,
    deck: Path,
    saved: dict[str, str],
    *,
    skip: tuple[int, ...] = (),
) -> tuple[dict, list[dict]]:
    """Puts each saved video back on its slide, in place of its still picture.

    One video at a time, so a request Google refuses costs that video only; the
    still picture stays and the report says so. It never stops a conversion.
    """
    summary = {"placed": 0, "failed": 0}
    try:
        clips = [c for c in find_clips(deck) if c.kind == "video" and c.slide not in skip]
    except Exception as error:  # noqa: BLE001  # the deck was read once already; never stop here
        _log("embedded_video_unreadable", 0, error)
        return summary, []
    if not clips:
        return summary, []
    try:
        presentation = await google.inspect(presentation_id)
    except ToolkitError as error:
        _log("embedded_video_not_placed", 0, error)
        summary["failed"] = len(clips)
        return summary, [_failed_note(len(clips), "video")]
    slides = presentation.get("slides", [])
    taken: dict[int, set[str]] = {}
    for number, clip in enumerate(clips):
        drive_id = saved.get(clip.part)
        slide = slides[clip.slide - 1] if 0 < clip.slide <= len(slides) else None
        if not drive_id or slide is None:
            summary["failed"] += 1
            continue
        used = taken.setdefault(clip.slide, set())
        still = _still(slide, _wanted(clip.box), used)
        requests = [_create_video(slide, f"wmt_clip_{clip.slide}_{number}", drive_id, clip.box)]
        if still:
            used.add(still)
            requests.append({"deleteObject": {"objectId": still}})
        try:
            await google.slides_batch(presentation_id, requests)
        except ToolkitError as error:
            _log("embedded_video_not_placed", clip.slide, error)
            summary["failed"] += 1
            continue
        summary["placed"] += 1
    notes: list[dict] = []
    if summary["placed"]:
        notes.append(
            warning(
                "embedded_video_placed",
                f"{_plural(summary['placed'], 'embedded video')} "
                f"{'was' if summary['placed'] == 1 else 'were'} put back on the slide from "
                "the saved copy in the conversion folder, in place of the still picture. "
                "Anyone who plays the deck needs access to that file, and Drive needs a few "
                "minutes before a new video plays.",
                classification=C.SUBSTITUTED,
                count=summary["placed"],
            )
        )
    if summary["failed"]:
        notes.append(_failed_note(summary["failed"], "video"))
    return summary, notes


def _failed_note(count: int, what: str) -> dict:
    code = "embedded_video_not_placed" if what == "video" else "sound_video_not_placed"
    return warning(
        code,
        f"{_plural(count, 'embedded ' + what if what == 'video' else 'sound')} could not be put "
        "back on its slide. The slide keeps its picture"
        + (" and the video is saved in the conversion folder." if what == "video" else "."),
        classification=C.UNSUPPORTED,
        count=count,
    )


# ---------------------------------------------------------------- sounds


def _card(poster: bytes | None, size: tuple[int, int] = (480, 270)) -> Image.Image:
    """The picture a wrapped sound shows: its own icon, on a dark card."""
    card = Image.new("RGB", size, (32, 33, 36))
    icon: Image.Image | None = None
    if poster:
        try:
            icon = Image.open(io.BytesIO(poster)).convert("RGBA")
        except Exception:  # noqa: BLE001  # an unreadable icon is drawn instead
            icon = None
    if icon is None:
        icon = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon)
        draw.polygon(
            [(30, 75), (80, 75), (125, 35), (125, 165), (80, 125), (30, 125)], fill="white"
        )
        for radius in (40, 62, 84):
            draw.arc(
                (130 - radius // 2, 100 - radius, 130 + radius, 100 + radius),
                -50,
                50,
                fill="white",
                width=9,
            )
    scale = min(size[1] * 0.45 / icon.height, size[0] * 0.45 / icon.width)
    icon = icon.resize((max(1, int(icon.width * scale)), max(1, int(icon.height * scale))))
    card.paste(icon, ((size[0] - icon.width) // 2, (size[1] - icon.height) // 2), icon)
    return card


def wrap_sound(deck: Path, clip: Clip, out: Path) -> None:
    """Writes `out`: an MP4 of the sound (its trim) over a card with its icon."""
    with zipfile.ZipFile(deck) as archive:
        if archive.getinfo(clip.part).file_size > MAX_MEDIA_BYTES:
            raise RuntimeError("The sound is too large to wrap.")
        audio = archive.read(clip.part)
        poster = archive.read(clip.poster) if clip.poster else None
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        sound = folder / ("sound" + (Path(clip.part).suffix or ".wav"))
        sound.write_bytes(audio)
        card = folder / "card.png"
        _card(poster).save(card)
        start, end = clip.trim or (0.0, 0.0)
        trim = f"atrim=start={start / 1000:.3f}" + (f":end={end / 1000:.3f}" if end > start else "")
        command = [
            _ffmpeg(), "-y", "-loglevel", "error",
            "-loop", "1", "-framerate", "5", "-i", str(card),
            "-i", str(sound),
            "-filter_complex", f"[1:a]{trim},asetpts=PTS-STARTPTS[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "5",
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            "-sn", "-dn", "-map_chapters", "-1", "-map_metadata", "-1",
            "-movflags", "+faststart", str(out),
        ]  # fmt: skip
        try:
            done = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603  # nosec B603 -- fixed argv, no shell
        except OSError as error:
            raise RuntimeError("ffmpeg is needed to wrap a sound in a video.") from error
        if done.returncode != 0:
            raise RuntimeError("ffmpeg could not wrap the sound: " + done.stderr[-300:])


def _sound_box(clip: Clip, page: tuple[float, float]) -> tuple[float, float, float, float]:
    """The video's box: centred on the icon, big enough to use, kept on the slide."""
    x, y, w, h = clip.box
    width = min(max(MIN_SOUND_WIDTH_PT, w), page[0])
    height = width * 9 / 16
    left = min(max(0.0, x + w / 2 - width / 2), max(0.0, page[0] - width))
    top = min(max(0.0, y + h / 2 - height / 2), max(0.0, page[1] - height))
    return left, top, width, height


async def place_sounds(
    google: Any,
    presentation_id: str,
    folder_id: str,
    deck: Path,
    *,
    skip: tuple[int, ...] = (),
    wrap: Any = wrap_sound,
) -> tuple[dict, list[dict]]:
    """Puts each sound back as a short video: saved in the folder, on its slide.

    The speaker icon is replaced by the video, which shows the same icon and
    plays the sound when pressed. A sound that cannot be wrapped or placed costs
    only itself and leaves its icon.
    """
    summary = {"placed": 0, "failed": 0}
    clips = [c for c in find_clips(deck) if c.kind == "audio" and c.slide not in skip]
    if not clips:
        return summary, []
    try:
        presentation = await google.inspect(presentation_id)
        page = (_pt(presentation["pageSize"]["width"]), _pt(presentation["pageSize"]["height"]))
    except (ToolkitError, KeyError) as error:
        _log("sound_video_not_placed", 0, error)
        summary["failed"] = len(clips)
        return summary, [_failed_note(len(clips), "sound")]
    slides = presentation.get("slides", [])
    taken: dict[int, set[str]] = {}
    for number, clip in enumerate(clips):
        slide = slides[clip.slide - 1] if 0 < clip.slide <= len(slides) else None
        if slide is None:
            summary["failed"] += 1
            continue
        with tempfile.TemporaryDirectory() as work:
            out = Path(work) / "sound.mp4"
            try:
                await asyncio.to_thread(wrap, deck, clip, out)
                saved = await google.upload(
                    out,
                    f"Slide {clip.slide} sound - {Path(clip.part).stem}.mp4",
                    "video/mp4",
                    folder_id,
                    retry=True,
                )
            except Exception as error:  # noqa: BLE001  # one sound never stops the rest
                _log("sound_video_not_placed", clip.slide, error)
                summary["failed"] += 1
                continue
        used = taken.setdefault(clip.slide, set())
        still = _still(slide, _wanted(clip.box), used)
        requests = [
            _create_video(
                slide, f"wmt_sound_{clip.slide}_{number}", saved["id"], _sound_box(clip, page)
            )
        ]
        if still:
            used.add(still)
            requests.append({"deleteObject": {"objectId": still}})
        try:
            await google.slides_batch(presentation_id, requests)
        except ToolkitError as error:
            _log("sound_video_not_placed", clip.slide, error)
            summary["failed"] += 1
            continue
        summary["placed"] += 1
    notes: list[dict] = []
    if summary["placed"]:
        notes.append(
            warning(
                "sound_video_placed",
                f"{_plural(summary['placed'], 'embedded sound')} "
                f"{'was' if summary['placed'] == 1 else 'were'} put back as a short video in "
                "place of the speaker icon: press it to play the sound. Slides cannot hold a "
                "sound itself. The videos are saved in the conversion folder, and anyone who "
                "plays the deck needs access to them.",
                classification=C.SUBSTITUTED,
                count=summary["placed"],
            )
        )
    if summary["failed"]:
        notes.append(_failed_note(summary["failed"], "sound"))
    return summary, notes


def main(argv: list[str] | None = None) -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Embedded video and sound in a deck.")
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser("find", help="list the videos and sounds that show on slides")
    find.add_argument("deck", type=Path)
    sounds = commands.add_parser(
        "sounds",
        help="wrap each sound in a video and put it on the converted deck "
        "(the token is read from GOOGLE_ACCESS_TOKEN; needs ffmpeg)",
    )
    sounds.add_argument("deck", type=Path, help="the original .pptx")
    sounds.add_argument("presentation", help="the converted Slides deck's id")
    sounds.add_argument("folder", help="the conversion folder's id")
    sounds.add_argument("--skip", default="", help="slide numbers to leave alone, such as 6,9")
    args = parser.parse_args(argv)
    if args.command == "find":
        print(
            json.dumps(
                [
                    {"slide": c.slide, "kind": c.kind, "part": c.part, "box": c.box}
                    for c in find_clips(args.deck)
                ],
                indent=2,
            )
        )
        return
    import httpx

    from .google import Google

    skip = tuple(int(n) for n in args.skip.split(",") if n.strip())

    async def go() -> None:
        async with httpx.AsyncClient(timeout=300) as client:
            google = Google(os.environ["GOOGLE_ACCESS_TOKEN"], client)
            summary, notes = await place_sounds(
                google, args.presentation, args.folder, args.deck, skip=skip
            )
            print(json.dumps(summary))
            print(json.dumps([n["code"] for n in notes]))

    asyncio.run(go())


if __name__ == "__main__":
    main()
