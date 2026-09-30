from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from html import unescape
from pathlib import Path

# Type annotation only; XML parsing always uses defusedxml.
from xml.etree.ElementTree import Element  # nosec B405

from defusedxml import ElementTree as SafeET

from .config import Settings
from .errors import ToolkitError
from .fonts import FontStatus, catalogue, compatibility
from .model import Compatibility as C
from .model import emu_to_points, warning
from .package import PPTX, Package, digest, without_overrides, without_relationships

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
}

# The start tag of a DrawingML <a:latin>, whatever its prefix. Matching whole
# start tags is what keeps slide *text* out of reach: a literal `"` needs no
# escaping in text content, so a lesson about HTML can contain the characters
# typeface="Segoe UI", but never the characters <a:latin in its text.
LATIN_TAG = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?latin\b[^>]*>")
TYPEFACE = re.compile(rb"(\stypeface\s*=\s*)([\"'])(.*?)\2")
CHARSET = re.compile(rb"\scharset\s*=\s*([\"'])(.*?)\1")
# Facts about the original face that are false once the name is replaced.
STALE_METADATA = re.compile(rb"\s(?:panose|pitchFamily|charset)\s*=\s*([\"']).*?\1")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def shape_name(node: Element) -> str:
    """The object's own name, as PowerPoint's selection pane shows it.

    For inserted audio and video PowerPoint uses the file's name, which is the
    closest thing a package keeps to the name the teacher gave the file.
    """
    for child in node:
        if local(child.tag).startswith("nv"):
            properties = child.find("p:cNvPr", NS)
            if properties is not None:
                return properties.get("name", "")
    return ""


def paragraphs(root: Element) -> list[dict]:
    result = []
    for p in root.findall(".//a:p", NS):
        runs = []
        for child in p:
            if local(child.tag) in {"r", "fld"}:
                prop = child.find("a:rPr", NS)
                text = child.find("a:t", NS)
                style: dict[str, object] = dict(prop.attrib) if prop is not None else {}
                latin = prop.find("a:latin", NS) if prop is not None else None
                font_family = latin.get("typeface") if latin is not None else None
                if font_family:
                    style["fontFamily"] = font_family
                    style["fontCompatibility"] = compatibility(font_family)
                runs.append(
                    {
                        "text": text.text or "" if text is not None else "",
                        "sourceStyle": style,
                    }
                )
            elif local(child.tag) == "br":
                runs.append({"text": "\n", "sourceStyle": {}})
        prop = p.find("a:pPr", NS)
        result.append({"runs": runs, "sourceStyle": dict(prop.attrib) if prop is not None else {}})
    return result


# Maps a shape's own coordinates to slide points: (scale x, scale y, shift x,
# shift y). A slide's top-level shapes are already in slide space; a group's
# children are in the group's chOff/chExt space, and groups nest.
Space = tuple[float, float, float, float]
SLIDE_SPACE: Space = (1.0, 1.0, 0.0, 0.0)


def _xfrm(element: Element) -> Element | None:
    return next((e for e in element.iter() if local(e.tag) == "xfrm"), None)


def _pair(xfrm: Element, kind: str, keys: tuple[str, str]) -> tuple[float, float] | None:
    node = next((e for e in xfrm if local(e.tag) == kind), None)
    if node is None:
        return None
    try:
        return emu_to_points(node.attrib[keys[0]]), emu_to_points(node.attrib[keys[1]])
    except (KeyError, ValueError) as exc:
        raise ToolkitError(
            "invalid_geometry", "The presentation contains invalid object coordinates."
        ) from exc


def geometry(element: Element, space: Space = SLIDE_SPACE) -> dict:
    """Bounds in slide points, with the source transform kept as written.

    A rotated or flipped group is mapped as if unrotated, the same way each
    shape's bounds are its unrotated box and its rotation is reported apart.
    """
    xfrm = _xfrm(element)
    if xfrm is None:
        return {"bounds": None, "rotation": None}
    off = _pair(xfrm, "off", ("x", "y"))
    ext = _pair(xfrm, "ext", ("cx", "cy"))
    bounds = None
    if off is not None and ext is not None:
        sx, sy, dx, dy = space
        bounds = {
            "x": dx + sx * off[0],
            "y": dy + sy * off[1],
            "width": sx * ext[0],
            "height": sy * ext[1],
        }
    return {
        "bounds": bounds,
        "rotation": int(xfrm.get("rot", "0")) / 60000,
        "sourceTransform": {
            "attributes": dict(xfrm.attrib),
            "children": [{"kind": local(e.tag), **e.attrib} for e in xfrm],
        },
    }


def child_space(group: Element, space: Space) -> Space:
    """The space a group's children are placed in, composed with the group's own."""
    xfrm = _xfrm(group)
    if xfrm is None:
        return space
    off = _pair(xfrm, "off", ("x", "y"))
    ext = _pair(xfrm, "ext", ("cx", "cy"))
    child_off = _pair(xfrm, "chOff", ("x", "y"))
    child_ext = _pair(xfrm, "chExt", ("cx", "cy"))
    if off is None or ext is None or child_off is None or child_ext is None:
        return space
    # A zero-sized child space has no scale to recover; keep the children's size.
    kx = ext[0] / child_ext[0] if child_ext[0] else 1.0
    ky = ext[1] / child_ext[1] if child_ext[1] else 1.0
    sx, sy, dx, dy = space
    return (
        sx * kx,
        sy * ky,
        dx + sx * (off[0] - kx * child_off[0]),
        dy + sy * (off[1] - ky * child_off[1]),
    )


def analyse(path: Path, output: Path, settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    package = Package(path, settings)
    try:
        return _analyse(package, path, output)
    finally:
        package.close()


def _analyse(package: Package, path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    asset_dir = output / "assets"
    asset_dir.mkdir(exist_ok=True)
    warnings = []
    assets: dict[str, dict] = {}
    part_assets: dict[str, str] = {}
    relationships: dict[str, list[dict]] = {}
    fonts: set[str] = set()
    declared_fonts: set[str] = set()
    resources = []
    for name in sorted(package.names):
        if name.endswith(".rels"):
            parent, filename = name.rsplit("/", 1) if "/" in name else ("", name)
            part = (
                ""
                if name == "_rels/.rels"
                else parent.removesuffix("_rels") + filename.removesuffix(".rels")
            )
            # The package root has no part name. Give it an explicit JSON key
            # because several otherwise-valid JSON consumers reject empty keys.
            relationships[part or "_package"] = package.relationships(part)
        if name.startswith(("ppt/media/", "ppt/embeddings/")):
            data = package.read(name)
            sha = digest(data)
            mime = package.mime(name)
            if sha not in assets:
                target = "assets/" + sha  # generated name, never an archive path
                (output / target).write_bytes(data)
                kind = (
                    mime.split("/", 1)[0]
                    if mime.startswith(("image/", "audio/", "video/"))
                    else "embedded"
                )
                assets[sha] = {
                    "id": sha,
                    "sha256": sha,
                    "path": target,
                    "mimeType": mime,
                    "kind": kind,
                    "byteLength": len(data),
                    "sourceParts": [],
                    "uses": [],
                    "status": "extracted",
                }
            assets[sha]["sourceParts"].append(name)
            part_assets[name] = sha
        if name.startswith("ppt/") and name.endswith(".xml"):
            root = package.xml(name)
            theme = name.startswith("ppt/theme/")
            for node in root.iter():
                typeface = node.get("typeface")
                # A theme's <a:font script="..."> entries are Office's standby
                # fonts for other writing systems, listed by every theme and
                # used only for text in that script: not fonts the deck needs.
                if theme and node.tag == f"{{{NS['a']}}}font":
                    continue
                if typeface and not typeface.startswith("+"):
                    (declared_fonts if theme else fonts).add(typeface)
            if name.startswith(
                (
                    "ppt/slideMasters/",
                    "ppt/slideLayouts/",
                    "ppt/theme/",
                    "ppt/charts/",
                    "ppt/notesSlides/",
                )
            ):
                resources.append(
                    {
                        "part": name,
                        "mimeType": package.mime(name),
                        "sha256": digest(package.read(name)),
                        "paragraphs": paragraphs(root),
                    }
                )
    for part, rels in relationships.items():
        for rel in rels:
            if rel["resolved"] in part_assets:
                assets[part_assets[rel["resolved"]]]["uses"].append(
                    {"part": part, "relationshipId": rel["id"], "relationshipType": rel["type"]}
                )
            if rel["missing"]:
                warnings.append(
                    warning(
                        "relationship_target_missing",
                        "A link inside the file points at a component that is not there. "
                        "The rest of the file was read; the link was ignored.",
                        part=part,
                        relationshipId=rel["id"],
                        classification=C.IGNORED,
                    )
                )
            if rel["external"]:
                warnings.append(
                    warning(
                        "external_link",
                        "An external link was recorded but not downloaded.",
                        part=part,
                        relationshipId=rel["id"],
                        classification=C.UNSUPPORTED,
                    )
                )
    presentation = package.xml("ppt/presentation.xml")
    if presentation.tag != f"{{{NS['p']}}}presentation":
        raise ToolkitError("unsupported_namespace", "This PowerPoint format is not supported yet.")
    size = presentation.find("p:sldSz", NS)
    if size is None:
        raise ToolkitError("missing_size", "The presentation has no slide dimensions.")
    try:
        width, height = emu_to_points(size.attrib["cx"]), emu_to_points(size.attrib["cy"])
        if width <= 0 or height <= 0:
            raise ValueError
    except (KeyError, ValueError) as exc:
        raise ToolkitError(
            "invalid_size", "The presentation has invalid slide dimensions."
        ) from exc
    presentation_rels = {r["id"]: r for r in package.relationships("ppt/presentation.xml")}
    slides = []
    seen_slides: set[str] = set()
    for order, sid in enumerate(presentation.findall("p:sldIdLst/p:sldId", NS)):
        rid = sid.get(f"{{{NS['r']}}}id", "")
        slide_ref = presentation_rels.get(rid)
        if (
            not slide_ref
            or slide_ref["external"]
            or slide_ref["resolved"] is None
            or not slide_ref["type"].endswith("/slide")
            or slide_ref["resolved"] in seen_slides
        ):
            raise ToolkitError("invalid_slide_order", "The presentation's slide order is invalid.")
        part = slide_ref["resolved"]
        seen_slides.add(part)
        root = package.xml(part)
        elements: list[dict] = []
        slide_rels = {r["id"]: r for r in package.relationships(part)}

        def walk(
            parent: Element,
            parent_id: str | None = None,
            space: Space = SLIDE_SPACE,
            *,
            order=order,
            elements=elements,
            slide_rels=slide_rels,
        ) -> None:
            for node in parent:
                tag = local(node.tag)
                if tag in {"nvGrpSpPr", "grpSpPr", "extLst"}:
                    if tag == "extLst":
                        warnings.append(
                            warning(
                                "extension",
                                "A slide extension needs review after import.",
                                slideIndex=order,
                                classification=C.UNSUPPORTED,
                            )
                        )
                    continue
                oid = f"slide_{order}_object_{len(elements)}"
                kind = {
                    "sp": "shape",
                    "pic": "image",
                    "graphicFrame": "unknown",
                    "cxnSp": "line",
                    "grpSp": "group",
                }.get(tag, "unknown")
                tables = node.findall(".//a:tbl", NS) if tag != "grpSp" else []
                charts = node.findall(".//c:chart", NS) if tag != "grpSp" else []
                pars = paragraphs(node) if tag != "grpSp" else []
                if tables:
                    kind = "table"
                elif charts:
                    kind = "chart"
                text_box = node.find("p:nvSpPr/p:cNvSpPr", NS)
                if text_box is not None and text_box.get("txBox") == "1":
                    kind = "text"
                obj = {
                    "id": oid,
                    "name": shape_name(node),
                    "type": kind,
                    "zIndex": len(elements),
                    "parentId": parent_id,
                    "paragraphs": pars,
                    "sourceKind": tag,
                    **geometry(node, space),
                    "relationshipIds": [],
                    "assetIds": [],
                    "warnings": [],
                    "classification": C.NATIVE if kind != "unknown" else C.UNSUPPORTED,
                    "verification": "pending_native_import",
                }
                for child in node.iter() if tag != "grpSp" else []:
                    for attr, relationship_id in child.attrib.items():
                        if attr.startswith("{" + NS["r"] + "}"):
                            obj["relationshipIds"].append(relationship_id)
                            target = slide_rels.get(relationship_id, {}).get("resolved")
                            if target in part_assets:
                                obj["assetIds"].append(part_assets[target])
                obj["assetIds"] = sorted(set(obj["assetIds"]))
                if tables:
                    obj["tables"] = [
                        {
                            "rows": [
                                [paragraphs(cell) for cell in row.findall("a:tc", NS)]
                                for row in table.findall("a:tr", NS)
                            ]
                        }
                        for table in tables
                    ]
                if kind in {"unknown", "chart", "group"}:
                    obj["warnings"].append(
                        warning(
                            "review_object",
                            "This object requires review after Google's import.",
                            classification=C.UNSUPPORTED if kind == "unknown" else C.NATIVE,
                        )
                    )
                elements.append(obj)
                if tag == "grpSp":
                    walk(node, oid, child_space(node, space))

        tree = root.find("p:cSld/p:spTree", NS)
        if tree is None:
            raise ToolkitError("invalid_slide", "A slide has no object tree.")
        walk(tree)
        for feature in ("transition", "timing"):
            if root.find("p:" + feature, NS) is not None:
                warnings.append(
                    warning(
                        feature,
                        "Animations or transitions may be omitted during conversion.",
                        slideIndex=order,
                        classification=C.IGNORED,
                    )
                )
        slides.append(
            {
                "id": f"slide_{order}",
                "index": order,
                "sourcePart": part,
                "width": width,
                "height": height,
                "unit": "pt",
                "elements": elements,
            }
        )
    if not slides:
        raise ToolkitError("no_slides", "The presentation contains no slides.")
    for asset in assets.values():
        if asset["kind"] == "video":
            warnings.append(
                warning(
                    "video_saved_separately",
                    "Google Slides does not import embedded video, so this video's slide "
                    "will show its still image. The video itself is saved in the "
                    "conversion folder in Drive.",
                    assetId=asset["id"],
                    classification=C.UNSUPPORTED,
                )
            )
        elif asset["kind"] in {"audio", "embedded"}:
            warnings.append(
                warning(
                    "embedded_asset",
                    "An embedded item was preserved separately; playback or editability needs review.",
                    assetId=asset["id"],
                    classification=C.UNSUPPORTED,
                )
            )
    font_catalogue = catalogue(fonts)
    declared_font_catalogue = catalogue(declared_fonts)
    font_requirements = catalogue(fonts | declared_fonts)
    for font in font_requirements:
        if font["status"] == FontStatus.SUBSTITUTED:
            warnings.append(
                warning(
                    "font_substitution",
                    "A font has a reviewed Google Fonts replacement candidate.",
                    font=font["name"],
                    replacement=font["replacement"],
                    confidence=font["confidence"],
                    manualReview=font["manualReview"],
                    classification=C.SUBSTITUTED,
                )
            )
        elif font["status"] == FontStatus.UNKNOWN:
            warnings.append(
                warning(
                    "font_unknown",
                    "A font has no reviewed replacement and needs manual review.",
                    font=font["name"],
                    classification=C.UNSUPPORTED,
                )
            )
    manifest = {
        "schemaVersion": "1.0",
        "source": {
            "type": "pptx",
            "sha256": digest(path.read_bytes()),
            "byteLength": path.stat().st_size,
        },
        "document": {"pageCount": len(slides), "widthPt": width, "heightPt": height},
        "pages": slides,
        "assets": assets,
        "resources": resources,
        "relationships": relationships,
        "fonts": font_catalogue,
        "declaredFonts": sorted(declared_fonts),
        "declaredFontCompatibility": declared_font_catalogue,
        "fontRequirements": font_requirements,
        "warnings": warnings,
    }
    report = analysis_report(manifest)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return manifest


def analysis_report(manifest: dict) -> dict:
    counts = Counter(e["type"] for page in manifest["pages"] for e in page["elements"])
    warnings = list(manifest["warnings"])
    for page in manifest["pages"]:
        for element in page["elements"]:
            warnings.extend(
                {**w, "slideIndex": page["index"], "elementId": element["id"]}
                for w in element["warnings"]
            )
    return {
        "schemaVersion": "1.0",
        "status": "analysed",
        "sourceSha256": manifest["source"]["sha256"],
        "pages": len(manifest["pages"]),
        "dimensionsPt": {
            "width": manifest["document"]["widthPt"],
            "height": manifest["document"]["heightPt"],
        },
        "elementCounts": dict(counts),
        "assetCounts": dict(Counter(a["kind"] for a in manifest["assets"].values())),
        "fonts": manifest.get("fontRequirements", manifest["fonts"]),
        "warnings": warnings,
        "verification": "not_converted",
        "classificationBasis": "Preflight candidates, not verified Google compatibility.",
    }


def _substitute_typefaces(data: bytes, applied: Counter[tuple[str, str]]) -> bytes:
    """Replace reviewed Latin typefaces without reserialising whole XML parts.

    Only `<a:latin>` is rewritten (issue #50). The shared service's candidates
    are Latin faces with no statement of East Asian or complex-script
    coverage, so `<a:ea>` and `<a:cs>` keep their families. `<a:sym>` and
    `<a:buFont>` name symbol and bullet fonts, whose glyphs are mapped by code
    point, and so does a Latin slot declaring the symbol character set. A
    rewritten tag loses the PANOSE, pitch and character set it carried: they
    describe the original face, not its replacement.
    """

    def replace(tag_match: re.Match[bytes]) -> bytes:
        tag = tag_match.group(0)
        match = TYPEFACE.search(tag)
        if match is None:
            return tag
        charset = CHARSET.search(tag)
        if charset is not None and charset.group(2).strip() in {b"2", b"02"}:
            return tag
        try:
            original = unescape(match.group(3).decode("utf-8"))
        except UnicodeDecodeError:
            return tag
        result = compatibility(original)
        replacement = result.get("replacement")
        if (
            result["status"] != FontStatus.SUBSTITUTED
            or result["manualReview"]
            or not isinstance(replacement, str)
        ):
            return tag
        applied[(original, replacement)] += 1
        encoded = (
            replacement.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .encode("utf-8")
        )
        quote = match.group(2)
        rewritten = tag[: match.start()] + match.group(1) + quote + encoded + quote
        return STALE_METADATA.sub(b"", rewritten + tag[match.end() :])

    return LATIN_TAG.sub(replace, data)


# --- embedded video (issue #36) ----------------------------------------------
#
# Google Slides does not import embedded video (docs/research.md), and the
# conversion already saves each video to Drive beside the deck. Sending the
# video to Google anyway only costs upload time and counts toward its 100 MB
# conversion limit, which is what a large deck usually exceeds. So a video is
# taken out before upload: its part, the relationships to it, and the markup
# that plays it. The picture element stays, with its poster frame, so the slide
# keeps the video's still image where the video was. Audio is left alone.
#
# The markup is edited as bytes, like the font rewrite, so nothing else in the
# part is re-serialised; the parser only decides what to remove, and checks
# the result. A part that fails the check keeps its video.

VIDEO_RELATIONSHIPS = ("/relationships/video", "/relationships/media")
_Q = rb"(?:[A-Za-z_][\w.-]*:)?"
PLAYS_MEDIA = re.compile(
    rb"<(?P<q>" + _Q + rb"(?:videoFile|quickTimeFile|media))\b(?P<attrs>[^>]*?)"
    rb"(?:/>|>.*?</(?P=q)>)",
    re.S,
)
REFERENCE = re.compile(rb"\s" + _Q + rb"(?:link|embed)\s*=\s*([\"'])(.*?)\1")
TIMING_VIDEO = re.compile(rb"<(?P<q>" + _Q + rb"video)\b[^>]*>(?P<body>.*?)</(?P=q)>", re.S)
SHAPE_TARGET = re.compile(rb"\sspid\s*=\s*([\"'])(.*?)\1")
# Left empty once their only child is gone. An empty p:ext is invalid (it
# must hold one element); an empty list is merely untidy. Only an extension
# (which always names its uri) counts: DrawingML's size tag is also "ext",
# and may be written <a:ext cx=".." cy=".."></a:ext> (#124).
EMPTIED = re.compile(
    rb"<(?P<q>" + _Q + rb"(?:ext(?=\s[^>]*\buri\s*=)|extLst|childTnLst))\b[^>]*>\s*</(?P=q)>"
)
SIZE = f"{{{NS['a']}}}ext"


def _rels_name(part: str) -> str:
    folder, _, base = part.rpartition("/")
    return f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"


def _values(pattern: re.Pattern[bytes], text: bytes) -> set[str]:
    return {m.group(2).decode("utf-8", "replace") for m in pattern.finditer(text)}


def _video_shapes(root: Element, rids: set[str]) -> set[str]:
    """The ids of picture shapes whose video is being removed."""
    shapes = set()
    r = f"{{{NS['r']}}}"
    for pic in root.iter(f"{{{NS['p']}}}pic"):
        plays = any(
            local(node.tag) in {"videoFile", "quickTimeFile", "media"}
            and {node.get(r + "link"), node.get(r + "embed")} & rids
            for node in pic.iter()
        )
        properties = pic.find("p:nvPicPr/p:cNvPr", NS)
        if plays and properties is not None and properties.get("id"):
            shapes.add(properties.get("id", ""))
    return shapes


def _strip_part(data: bytes, rids: set[str]) -> bytes | None:
    """The part without the markup that plays these relationships, or None if
    the result could not be confirmed sound."""
    try:
        before = SafeET.fromstring(data)
    except SafeET.ParseError:
        return None
    shapes = _video_shapes(before, rids)
    result = PLAYS_MEDIA.sub(
        lambda m: b"" if _values(REFERENCE, m["attrs"]) & rids else m.group(0), data
    )
    result = TIMING_VIDEO.sub(
        lambda m: b"" if _values(SHAPE_TARGET, m["body"]) & shapes else m.group(0), result
    )
    while (tidier := EMPTIED.sub(b"", result)) != result:
        result = tidier
    try:
        after = SafeET.fromstring(result)
    except SafeET.ParseError:
        return None
    pictures = f"{{{NS['p']}}}pic"
    if sum(1 for _ in after.iter(pictures)) != sum(1 for _ in before.iter(pictures)):
        return None  # every picture, poster frames included, must survive
    if sum(1 for _ in after.iter(SIZE)) != sum(1 for _ in before.iter(SIZE)):
        return None  # and every shape's size
    r = f"{{{NS['r']}}}"
    for node in after.iter():
        if any(key.startswith(r) and value in rids for key, value in node.attrib.items()):
            return None
    return result


def strip_videos(package: Package, parts: dict[str, bytes]) -> list[dict]:
    """Takes embedded video out of `parts` (name -> bytes, edited in place).

    Returns what was removed. A video is removed only if every relationship
    to it is a video or media one -- a file also used as a picture stays --
    and only if every part that plays it can be edited and checked.
    """
    references: dict[str, list[tuple[str, str, bool]]] = {}
    for rels in sorted(n for n in package.names if n.endswith(".rels") and n != "_rels/.rels"):
        folder, _, base = rels.rpartition("/")
        part = folder.removesuffix("_rels") + base.removesuffix(".rels")
        for rel in package.relationships(part):
            if rel["external"] or not rel["resolved"]:
                continue
            is_video = rel["type"].endswith(VIDEO_RELATIONSHIPS)
            references.setdefault(rel["resolved"], []).append((part, rel["id"], is_video))
    videos = {
        target
        for target, refs in references.items()
        if package.mime(target).startswith("video/") and all(v for _, _, v in refs)
    }
    while videos:
        by_part: dict[str, set[str]] = {}
        for target in videos:
            for part, rid, _ in references[target]:
                by_part.setdefault(part, set()).add(rid)
        edited: dict[str, bytes] = {}
        refused: set[str] = set()
        for part, rids in sorted(by_part.items()):
            source = parts.get(part) or package.read(part, package.settings.max_xml_bytes)
            stripped = _strip_part(source, rids)
            rels = _rels_name(part)
            links = (
                None
                if stripped is None
                else without_relationships(parts.get(rels) or package.read(rels), rids)
            )
            if stripped is None or links is None:
                refused |= {t for t in videos if any(p == part for p, _, _ in references[t])}
                continue
            edited[part] = stripped
            edited[rels] = links
        if refused:
            videos -= refused
            continue
        types = without_overrides(
            parts.get("[Content_Types].xml") or package.read("[Content_Types].xml"), videos
        )
        if types is None:
            return []  # nothing is changed: `parts` is only updated below
        edited["[Content_Types].xml"] = types
        parts.update(edited)
        break
    if not videos:
        return []
    return [
        {
            "part": target,
            "bytes": package.zip.getinfo(target).file_size,
            "usedBy": sorted({p for p, _, _ in references[target]}),
        }
        for target in sorted(videos)
    ]


def render(package: Package, destination: Path) -> dict:
    """Write a Google-ready PPTX with reviewed font candidates applied."""
    rewritten: dict[str, bytes] = {}
    applied: Counter[tuple[str, str]] = Counter()
    for name in sorted(package.names):
        if name.endswith(".xml"):
            source = package.read(name, package.settings.max_xml_bytes)
            target = _substitute_typefaces(source, applied)
            if target != source:
                rewritten[name] = target

    videos = strip_videos(package, rewritten)
    removed = {video["part"] for video in videos}

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
        for name in sorted(package.names - removed):
            out.writestr(name, rewritten.get(name) or package.read(name))

    return {
        "fontSubstitutions": [
            {
                "original": original,
                "replacement": replacement,
                "occurrences": count,
                "classification": C.SUBSTITUTED,
            }
            for (original, replacement), count in sorted(applied.items())
        ],
        "rewrittenParts": sorted(rewritten),
        "videosRemoved": videos,
    }


def render_path(source: Path, destination: Path, settings: Settings) -> dict:
    package = Package(source, settings, PPTX)
    try:
        return render(package, destination)
    finally:
        package.close()
