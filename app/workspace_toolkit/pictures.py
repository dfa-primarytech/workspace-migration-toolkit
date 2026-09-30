"""Opt-in: make pictures smaller before a file goes to Google (issue #36, step 3).

A large deck or document is usually large because of its photographs: a phone
photo drawn three inches wide carries several times the pixels anyone will
see, and a photo pasted into Office is stored as PNG, often several times the
size of the same photo as JPEG. This does what PowerPoint's own Compress
Pictures does, to the converted copy only -- the person's file is untouched:

* a picture is reduced to the size it is drawn at, at 220 pixels per inch
  (PowerPoint's default), allowing for any crop;
* a photograph stored as PNG is re-saved as JPEG.

It changes pictures a person will see, so it only ever runs when asked for.
Anything it cannot be sure about is left alone: a picture drawn somewhere
other than a plain picture frame (a shape fill, a background, a legacy VML
image), a format other than PNG or JPEG, a JPEG with a rotation flag (Office
and Google disagree on those), a picture with transparency or few colours --
a diagram, a screenshot, text -- which stays PNG, and any result that is not
at least 10% smaller.

Runs in the analysis worker, after rendering, on `converted.<ext>`, the file
that is uploaded. The same code serves PowerPoint and Word, because a picture
frame is the same DrawingML element in both.
"""

from __future__ import annotations

import io
import os
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Type annotation only; XML parsing always uses defusedxml (via Package.xml).
from xml.etree.ElementTree import Element  # nosec B405

from PIL import Image

from .config import Settings
from .package import RELATIONSHIPS, Format, Package, with_default, without_overrides

PPI = 220
EMU_PER_INCH = 914_400
MIN_BYTES = 100 * 1024  # smaller pictures are not worth touching
MIN_SAVING = 0.10
JPEG_QUALITY = 85
# Beyond this Pillow refuses to decode: phone photos are 12 to 50 megapixels,
# and a crafted image claiming billions would otherwise exhaust memory.
MAX_PIXELS = 60_000_000
PHOTO_COLOURS = 4096  # a 256 px sample with more distinct colours is a photograph

R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
IMAGE_RELATIONSHIP = "/relationships/image"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass
class Plan:
    """What one picture part may become: the pixels it needs, at most."""

    width: int = 0
    height: int = 0
    unknown: bool = False  # drawn somewhere we cannot measure: leave it alone
    references: list[tuple[str, str]] = field(default_factory=list)  # (rels part, rid)


def _needed(pic: Element) -> tuple[int, int] | None:
    """Pixels a picture frame needs at PPI, allowing for its crop."""
    xfrm = next((e for e in pic.iter() if local(e.tag) == "xfrm"), None)
    ext = next((e for e in xfrm if local(e.tag) == "ext"), None) if xfrm is not None else None
    if ext is None:
        return None
    try:
        cx, cy = int(ext.get("cx", "0")), int(ext.get("cy", "0"))
    except ValueError:
        return None
    if cx <= 0 or cy <= 0:
        return None
    crop = next((e for e in pic.iter() if local(e.tag) == "srcRect"), None)

    def visible(a: str, b: str) -> float:
        if crop is None:
            return 1.0
        try:
            shown = 1 - (int(crop.get(a, "0")) + int(crop.get(b, "0"))) / 100_000
        except ValueError:
            return 1.0
        return max(shown, 0.05)

    width = cx / EMU_PER_INCH * PPI / visible("l", "r")
    height = cy / EMU_PER_INCH * PPI / visible("t", "b")
    return max(1, round(width)), max(1, round(height))


def plan(package: Package) -> dict[str, Plan]:
    """Every picture part, with the largest size it is drawn at anywhere."""
    plans: dict[str, Plan] = {}
    for rels in sorted(n for n in package.names if n.endswith(".rels") and n != "_rels/.rels"):
        folder, _, base = rels.rpartition("/")
        part = folder.removesuffix("_rels") + base.removesuffix(".rels")
        images = {
            rel["id"]: rel["resolved"]
            for rel in package.relationships(part)
            if rel["type"].endswith(IMAGE_RELATIONSHIP) and not rel["external"] and rel["resolved"]
        }
        if not images:
            continue
        for rid, target in images.items():
            plans.setdefault(target, Plan()).references.append((rels, rid))
        if not part.endswith(".xml") or part not in package.names:
            for target in images.values():
                plans[target].unknown = True
            continue
        root = package.xml(part)
        # A group can scale what it holds, so a grouped picture's own size is
        # not what is drawn: treat it as unmeasured.
        grouped = {
            id(e)
            for group in root.iter()
            if local(group.tag) in {"grpSp", "wgp"}
            for e in group.iter()
            if local(e.tag) == "pic"
        }
        measured: set[int] = set()
        for pic in (e for e in root.iter() if local(e.tag) == "pic" and id(e) not in grouped):
            size = _needed(pic)
            for blip in (e for e in pic.iter() if local(e.tag) == "blip"):
                rid = blip.get(f"{{{R}}}embed")
                if rid in images and size is not None:
                    item = plans[images[rid]]
                    item.width, item.height = max(item.width, size[0]), max(item.height, size[1])
                    measured.add(id(blip))
        # Any other use -- a fill, a background, VML, a linked copy -- is
        # drawn at a size we have not measured.
        for node in root.iter():
            if id(node) in measured:
                continue
            for key, value in node.attrib.items():
                if key.startswith(f"{{{R}}}") and value in images:
                    plans[images[value]].unknown = True
    return plans


def _is_photo(image: Image.Image) -> bool:
    sample = image.convert("RGB")
    sample.thumbnail((256, 256))
    return sample.getcolors(maxcolors=PHOTO_COLOURS) is None


def _transparent(image: Image.Image) -> bool:
    if "transparency" in image.info:
        return True
    if image.mode in {"RGBA", "LA", "PA"}:
        # Any pixel less than fully opaque: the first 255 histogram bins.
        return sum(image.getchannel("A").histogram()[:255]) > 0
    return False


def shrink(data: bytes, mime: str, width: int, height: int) -> tuple[bytes, str, str] | str:
    """(new bytes, new mime, what was done), or the reason it was left alone."""
    if len(data) < MIN_BYTES:
        return "small"
    if mime not in {"image/png", "image/jpeg"}:
        return "format"
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image: Image.Image = Image.open(io.BytesIO(data))
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "unreadable"
    if mime == "image/jpeg":
        if image.getexif().get(0x0112, 1) != 1:
            return "rotated"
        if image.mode not in {"RGB", "L"}:
            return "colour"  # CMYK and the like: leave the colours alone
    # The larger of the two, so neither dimension drops below what is shown
    # (a crop or a stretched frame can make the two disagree).
    scale = min(1.0, max(width / image.width, height / image.height))
    resized = scale < 0.95
    to_jpeg = mime == "image/png" and not _transparent(image) and _is_photo(image)
    if not resized and not to_jpeg:
        return "already small"
    profile = image.info.get("icc_profile")  # kept, so colours do not shift
    if resized:
        if image.mode in {"P", "1"}:  # otherwise Pillow falls back to its crudest resize
            image = image.convert("RGBA" if _transparent(image) else "RGB")
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    extra = {"icc_profile": profile} if profile else {}
    if to_jpeg or mime == "image/jpeg":
        image = image if image.mode in {"RGB", "L"} else image.convert("RGB")
        image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, **extra)
        new_mime = "image/jpeg"
    else:
        image.save(out, "PNG", optimize=True, **extra)
        new_mime = "image/png"
    if len(out.getvalue()) > len(data) * (1 - MIN_SAVING):
        return "no saving"
    done = "resized" if resized else "re-saved"
    if to_jpeg:
        done += " as JPEG"
    return out.getvalue(), new_mime, done


def _retarget(data: bytes, rid: str, old: str, new: str) -> bytes | None:
    """The .rels with one relationship's Target renamed, or None if it could not be."""
    changed = False

    def edit(match: re.Match[bytes]) -> bytes:
        nonlocal changed
        tag = match.group(0)
        if not re.search(rb"\sId\s*=\s*([\"'])" + re.escape(rid.encode()) + rb"\1", tag):
            return tag
        target = re.search(rb"(\sTarget\s*=\s*([\"']))(.*?)(\2)", tag)
        if target is None or not target.group(3).endswith(old.encode()):
            return tag
        changed = True
        value = target.group(3)[: -len(old.encode())] + new.encode()
        return tag[: target.start(3)] + value + tag[target.end(3) :]

    result = RELATIONSHIPS.sub(edit, data)  # empty or paired tags alike
    return result if changed else None


def compress(path: Path, settings: Settings, fmt: Format) -> dict:
    """Rewrites `path` in place with smaller pictures. Returns what changed."""
    before = path.stat().st_size
    package = Package(path, settings, fmt)
    try:
        plans = plan(package)
        replaced: dict[str, bytes] = {}  # part name -> new bytes (possibly under a new name)
        renames: dict[str, str] = {}
        edited: dict[str, bytes] = {}
        done: list[dict] = []
        skipped: dict[str, int] = {}
        for target, item in sorted(plans.items()):
            if item.unknown or not item.width:
                skipped["not measurable"] = skipped.get("not measurable", 0) + 1
                continue
            data = package.read(target)
            result = shrink(data, package.mime(target).lower(), item.width, item.height)
            if isinstance(result, str):
                skipped[result] = skipped.get(result, 0) + 1
                continue
            new_data, new_mime, how = result
            name = target
            if new_mime != package.mime(target).lower():
                stem = target.rsplit(".", 1)[0]
                name = stem + ".jpeg"
                while name in package.names or name in renames.values():
                    stem += "-small"
                    name = stem + ".jpeg"
                old_base, new_base = target.rsplit("/", 1)[-1], name.rsplit("/", 1)[-1]
                pending = dict(edited)
                for rels, rid in item.references:
                    source = pending.get(rels) or package.read(rels)
                    renamed = _retarget(source, rid, old_base, new_base)
                    if renamed is None:
                        break
                    pending[rels] = renamed
                else:
                    edited = pending
                    renames[target] = name
                    replaced[target] = new_data
                    done.append(_entry(target, name, data, new_data, how))
                    continue
                skipped["could not rename"] = skipped.get("could not rename", 0) + 1
                continue
            replaced[target] = new_data
            done.append(_entry(target, name, data, new_data, how))
        if not done:
            return {
                "picturesCompressed": [],
                "skipped": skipped,
                "bytesBefore": before,
                "bytesAfter": before,
            }
        types: bytes | None = package.read("[Content_Types].xml")
        if renames and types is not None:
            # The old picture's override goes, and a JPEG is declared, in
            # whatever prefix the file uses (#137). Unconfirmed: change nothing.
            types = without_overrides(types, set(renames))
            if types is not None:
                types = with_default(types, "jpeg", "image/jpeg")
        if types is None:
            skipped["content types not editable"] = len(done)
            return {
                "picturesCompressed": [],
                "skipped": skipped,
                "bytesBefore": before,
                "bytesAfter": before,
            }
        edited["[Content_Types].xml"] = types
        temporary = path.with_name(path.name + ".smaller")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as out:
            for name in sorted(package.names):
                if name in replaced:
                    # Already compressed: storing is faster and no larger.
                    out.writestr(renames.get(name, name), replaced[name], zipfile.ZIP_STORED)
                else:
                    out.writestr(name, edited.get(name) or package.read(name))
    finally:
        package.close()
    os.replace(temporary, path)
    return {
        "picturesCompressed": done,
        "skipped": skipped,
        "bytesBefore": before,
        "bytesAfter": path.stat().st_size,
    }


def _entry(old: str, new: str, before: bytes, after: bytes, how: str) -> dict:
    return {
        "part": old,
        "newPart": new,
        "bytesBefore": len(before),
        "bytesAfter": len(after),
        "change": how,
    }
