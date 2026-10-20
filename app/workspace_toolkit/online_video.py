"""Online videos in a PowerPoint deck, put back into the Slides deck.

PowerPoint keeps an online video as a picture (the still frame) whose video
link is an external address. Google's import keeps the picture and drops the
link, so the video vanished with no word. After the import this adds each
YouTube video back with the Slides API's own video element, where its still
picture was. Other providers (Vimeo, SharePoint, OneDrive, SlideShare) cannot
play inside Slides, so their picture is given the link instead: a click in
present mode opens the video.

An address is only ever read, never fetched. Nothing here may fail a
conversion: a refused request leaves the still picture where it was and says so.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning

logger = logging.getLogger(__name__)

# What a YouTube video id is: eleven of these characters, nothing more.
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_DOMAINS = ("youtube.com", "youtube-nocookie.com")
# "75", "75s" or "1h2m3s", as YouTube writes a start time.
START_TIME = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?")
PROVIDER_NAMES = {
    "youtube": "YouTube",
    "vimeo": "Vimeo",
    "slideshare": "SlideShare",
    "sharepoint": "SharePoint",
    "onedrive": "OneDrive",
    "other": "online",
}
# How near, in points, a picture must be to the video's place to be its still.
TOLERANCE_PT = 4.0
EMU_PER_PT = 12700


def _on(host: str, *domains: str) -> bool:
    """Whether `host` is one of these domains or a subdomain of one."""
    return any(host == d or host.endswith("." + d) for d in domains)


def _seconds(text: str | None) -> int | None:
    if not text:
        return None
    found = START_TIME.fullmatch(text.strip().lower())
    if not found or not any(found.groups()):
        return None
    hours, minutes, seconds = (int(part or 0) for part in found.groups())
    return hours * 3600 + minutes * 60 + seconds


def classify(url: str) -> dict:
    """The provider of a video address, and for YouTube its id and start time."""
    result: dict[str, Any] = {"provider": "other", "videoId": None, "start": None}
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return result
    if parts.scheme.lower() not in ("http", "https") or not host:
        return result
    query = parse_qs(parts.query)
    if host == "youtu.be" or _on(host, *YOUTUBE_DOMAINS):
        result["provider"] = "youtube"
        path = [p for p in parts.path.split("/") if p]
        if host == "youtu.be":
            candidate = path[0] if path else ""
        elif path and path[0] in ("embed", "shorts", "live", "v") and len(path) > 1:
            candidate = path[1]
        else:
            candidate = (query.get("v") or [""])[0]
        if VIDEO_ID.fullmatch(candidate):
            result["videoId"] = candidate
            result["start"] = _seconds((query.get("start") or query.get("t") or [""])[0])
        return result
    if _on(host, "vimeo.com"):
        result["provider"] = "vimeo"
    elif _on(host, "slideshare.net"):
        result["provider"] = "slideshare"
    elif _on(host, "sharepoint.com"):
        result["provider"] = "sharepoint"
    elif _on(host, "onedrive.live.com", "1drv.ms", "onedrive.com"):
        result["provider"] = "onedrive"
    return result


def _points(value: dict | None) -> float | None:
    """A Slides dimension in points, whichever unit it is stated in."""
    if not value or "magnitude" not in value:
        return None
    return value["magnitude"] / (1 if value.get("unit") == "PT" else EMU_PER_PT)


def _bounds(element: dict) -> tuple[float, float, float, float] | None:
    size, transform = element.get("size") or {}, element.get("transform") or {}
    width, height = _points(size.get("width")), _points(size.get("height"))
    if width is None or height is None:
        return None
    unit = transform.get("unit")
    divide = 1 if unit == "PT" else EMU_PER_PT
    x, y = transform.get("translateX", 0) / divide, transform.get("translateY", 0) / divide
    return x, y, width * transform.get("scaleX", 1), height * transform.get("scaleY", 1)


def _still(slide: dict, wanted: dict, taken: set[str]) -> str | None:
    """The picture on `slide` standing where the video's still frame was."""
    box = (wanted["x"], wanted["y"], wanted["width"], wanted["height"])
    best: tuple[float, str] | None = None
    for element in slide.get("pageElements", []):
        name = element.get("objectId", "")
        if "image" not in element or name in taken:
            continue
        found = _bounds(element)
        if found is None:
            continue
        gaps = [abs(a - b) for a, b in zip(found, box, strict=True)]
        if max(gaps) <= TOLERANCE_PT and (best is None or sum(gaps) < best[0]):
            best = (sum(gaps), name)
    return best[1] if best else None


def _requests(slide: dict, video: dict, name: str, still: str | None) -> list[dict]:
    box = video["bounds"]
    info = video["onlineVideo"]
    if info["videoId"]:
        requests: list[dict] = [
            {
                "createVideo": {
                    "objectId": name,
                    "elementProperties": {
                        "pageObjectId": slide["objectId"],
                        "size": {
                            "width": {"magnitude": box["width"], "unit": "PT"},
                            "height": {"magnitude": box["height"], "unit": "PT"},
                        },
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": box["x"],
                            "translateY": box["y"],
                            "unit": "PT",
                        },
                    },
                    "source": "YOUTUBE",
                    "id": info["videoId"],
                }
            }
        ]
        if info.get("start"):
            requests.append(
                {
                    "updateVideoProperties": {
                        "objectId": name,
                        "videoProperties": {"start": info["start"]},
                        "fields": "start",
                    }
                }
            )
        if still:
            requests.append({"deleteObject": {"objectId": still}})
        return requests
    return [
        {
            "updateImageProperties": {
                "objectId": still,
                "imageProperties": {"link": {"url": info["url"]}},
                "fields": "link",
            }
        }
    ]


def _plural(count: int, what: str) -> str:
    return f"{count} {what}{'' if count == 1 else 's'}"


async def apply(
    google: Any, presentation_id: str, presentation: dict, manifest: dict
) -> tuple[dict, list[dict]]:
    """Puts the deck's online videos into the imported presentation.

    Returns what was done, and the notes for the report. One video at a time,
    so a request Google refuses costs that video and no other.
    """
    summary = {"embedded": 0, "linked": 0, "failed": 0}
    slides = presentation.get("slides", [])
    providers: set[str] = set()
    for page in manifest["pages"]:
        videos = [e for e in page["elements"] if e.get("onlineVideo")]
        slide = slides[page["index"]] if 0 <= page["index"] < len(slides) else None
        taken: set[str] = set()
        for number, video in enumerate(videos):
            info = video["onlineVideo"]
            usable = info["videoId"] or (
                urlsplit(info["url"]).scheme.lower() in ("http", "https") and info["provider"]
            )
            still = _still(slide, video["bounds"], taken) if slide and video.get("bounds") else None
            if slide is None or not usable or (not info["videoId"] and still is None):
                summary["failed"] += 1
                continue
            if still:
                taken.add(still)
            name = f"wmt_video_{page['index']}_{number}"
            try:
                await google.slides_batch(presentation_id, _requests(slide, video, name, still))
            except ToolkitError as error:
                summary["failed"] += 1
                logger.warning(
                    json.dumps(
                        {
                            "event": "online_video_refused",
                            "provider": info["provider"],
                            "detail": str(error.detail or "")[:300],
                        }
                    )
                )
                continue
            if info["videoId"]:
                summary["embedded"] += 1
            else:
                summary["linked"] += 1
                providers.add(PROVIDER_NAMES.get(info["provider"], "online"))
    notes: list[dict] = []
    if summary["embedded"]:
        notes.append(
            warning(
                "online_video_embedded",
                f"{_plural(summary['embedded'], 'YouTube video')} "
                f"{'was' if summary['embedded'] == 1 else 'were'} added to the slides, "
                "in place of the still picture.",
                classification=C.SUBSTITUTED,
                count=summary["embedded"],
            )
        )
    if summary["linked"]:
        names = ", ".join(sorted(providers))
        notes.append(
            warning(
                "online_video_link_only",
                f"{_plural(summary['linked'], 'online video')} ({names}) cannot play inside "
                "Google Slides. The still picture links to the video instead: click it "
                "in present mode.",
                classification=C.SUBSTITUTED,
                count=summary["linked"],
            )
        )
    if summary["failed"]:
        notes.append(
            warning(
                "online_video_not_added",
                f"{_plural(summary['failed'], 'online video')} could not be put back. "
                "The slide keeps the still picture.",
                classification=C.UNSUPPORTED,
                count=summary["failed"],
            )
        )
    return summary, notes
