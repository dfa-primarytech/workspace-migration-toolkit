"""DOCX source parser and Google Docs renderer.

Google's importer does not fail loudly on floating shapes -- it quietly
reinterprets them, turning text boxes into uneditable drawings and losing
legacy pictures. The fix is to rewrite the offending constructs *before* Drive
sees the file, into ones the importer handles well.

Per PROJECT.md section 4 this module keeps the two halves separate:

  parse()   docx package -> intermediate model. Knows Word, not Google.
  render()  intermediate model + package -> a .docx Google imports faithfully.
            Knows what Google accepts, not why Word wrote it that way.

The single most valuable fact encoded here, verified against the live importer
rather than inferred: **Google honours OOXML floating-table positioning**. A
table carrying <w:tblpPr> with tblpX=7200, tblpY=2880 anchored to the page
imports to exactly 5in from the page left and 2in down, with text wrapping. So
a text box can become a table that keeps *both* its editable text and its
position, instead of trading one for the other.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# Type annotation and serialisation only; parsing always uses defusedxml.
from xml.etree.ElementTree import Element, register_namespace  # nosec B405

from .config import Settings
from .model import Compatibility as C
from .model import emu_to_points, warning
from .package import DOCX, Package, digest

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    # OMML. Without this, equations re-serialise under a generated prefix --
    # still valid, but it churns every equation in the output for no reason
    # and makes a diff of two conversions unreadable.
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}

# Keep the conventional prefixes on output. Word tolerates any prefix, but
# mc:Ignorable names prefixes as *text*, so renaming them would leave a root
# attribute pointing at prefixes that no longer exist.
for _prefix, _uri in NS.items():
    register_namespace(_prefix, _uri)

EMU_PER_INCH = 914400
EMU_PER_DXA = 635  # a dxa is 1/20 pt; 914400 / 1440
DXA_PER_POINT = 20

# Graphic types Google cannot turn into editable content. Listing charts and
# diagrams explicitly matters: SmartArt often carries a fallback <a:blip>, so
# without an entry here it classifies as a plain picture and can be discarded
# as a backing image. Being on this list makes preservation deliberate.
UNSUPPORTED_GRAPHICS = {
    "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup": "grouped shape",
    "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas": "drawing canvas",
    "http://schemas.openxmlformats.org/drawingml/2006/chart": "chart",
    "http://schemas.microsoft.com/office/drawing/2014/chartex": "chart",
    "http://schemas.openxmlformats.org/drawingml/2006/diagram": "SmartArt diagram",
}

# Word's positioning frames map onto the table-positioning ones directly.
ANCHOR_FRAMES = {
    "page": "page",
    "margin": "margin",
    "leftMargin": "margin",
    "rightMargin": "margin",
    "topMargin": "margin",
    "bottomMargin": "margin",
    "insideMargin": "margin",
    "outsideMargin": "margin",
    "column": "text",
    "character": "text",
    "paragraph": "text",
    "line": "text",
}

ALIGN_KEYWORDS = {"left", "right", "center", "inside", "outside", "top", "bottom"}

# Two anchors count as occupying the same rectangle when they agree this
# closely. Measured spreads in real card layouts are around 0.01in.
COINCIDENT_TOL_EMU = round(0.06 * EMU_PER_INCH)
COINCIDENT_SIZE_TOL = 0.03


def q(prefix: str, tag: str) -> str:
    return "{" + NS[prefix] + "}" + tag


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parents(root: Element) -> dict[Element, Element]:
    """ElementTree has no parent pointers, so build the map a pass needs.

    Rebuilt per pass rather than maintained across mutations: cheap, and it
    cannot drift out of step with the tree.
    """
    return {child: parent for parent in root.iter() for child in parent}


def emu(value: str | None) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def to_dxa(value: int) -> int:
    return round(value / EMU_PER_DXA)


# --------------------------------------------------------------------------
# Parser: Word in, intermediate model out. Knows nothing about Google.
# --------------------------------------------------------------------------


def graphic_uri(anchor: Element) -> str | None:
    data = anchor.find(".//" + q("a", "graphicData"))
    return data.get("uri") if data is not None else None


def classify(anchor: Element) -> tuple[str, str]:
    """Returns (kind, label). Kind drives the transform; label names it to users."""
    if anchor.find(".//" + q("w14", "contentPart")) is not None:
        return "ink", "ink annotation"
    uri = graphic_uri(anchor)
    if uri in UNSUPPORTED_GRAPHICS:
        return "unsupported", UNSUPPORTED_GRAPHICS[uri]
    if anchor.find(".//" + q("w", "txbxContent")) is not None:
        return "textbox", "text box"
    blip = anchor.find(".//" + q("a", "blip"))
    if blip is not None and anchor.find(q("wp", "extent")) is not None:
        return "picture", "picture"
    return "unsupported", "floating object"


def anchor_position(anchor: Element, axis: str) -> dict | None:
    """Reads <wp:positionH>/<wp:positionV> as structure, not a single number.

    A keyword alignment and an absolute offset become different attributes on
    the table (tblpXSpec vs tblpX), so the distinction has to survive.
    """
    pos = anchor.find(q("wp", "position" + axis))
    if pos is None:
        return None
    frame = ANCHOR_FRAMES.get(pos.get("relativeFrom") or "", "text")
    offset = pos.find(q("wp", "posOffset"))
    if offset is not None:
        value = emu((offset.text or "").strip())
        if value is not None:
            return {"mode": "offset", "emu": value, "frame": frame}
    align = pos.find(q("wp", "align"))
    if align is not None:
        keyword = (align.text or "").strip()
        if keyword in ALIGN_KEYWORDS:
            return {"mode": "align", "align": keyword, "frame": frame}
    return None


def anchor_extent(anchor: Element) -> dict | None:
    extent = anchor.find(q("wp", "extent"))
    if extent is None:
        return None
    cx, cy = emu(extent.get("cx")), emu(extent.get("cy"))
    return None if cx is None or cy is None else {"cx": cx, "cy": cy}


def bounds(position_h: dict | None, position_v: dict | None, extent: dict | None) -> dict | None:
    if extent is None:
        return None
    box: dict = {
        "width": emu_to_points(extent["cx"]),
        "height": emu_to_points(extent["cy"]),
    }
    for key, pos in (("x", position_h), ("y", position_v)):
        box[key] = emu_to_points(pos["emu"]) if pos and pos["mode"] == "offset" else None
    return box


ELEMENT_TYPES = {
    "textbox": "text",
    "picture": "image",
    "ink": "shape",
    "unsupported": "unknown",
}

COMPATIBILITY = {
    # A text box becomes a positioned table: a different construct reaching the
    # same result, which is what SUBSTITUTED means.
    "textbox": C.SUBSTITUTED,
    "picture": C.NATIVE,
    "ink": C.IGNORED,
    "unsupported": C.UNSUPPORTED,
}


def parse(package: Package, filename: str, source_sha: str) -> dict:
    """Builds the intermediate model. Source-format knowledge stops here."""
    root = package.xml(DOCX.main_part)
    body = root.find(q("w", "body"))
    if body is None:
        return empty_manifest(filename, source_sha)

    sections = page_sizes(body)
    buckets: list[list[dict]] = [[] for _ in sections]
    section_of = section_index(body, len(sections))

    # Anchors inside mc:Fallback are a legacy restatement of the shape in the
    # sibling mc:Choice, not extra content. Counting them would double every
    # shape Word wrote twice -- and make a text box's own fallback look like a
    # separate picture sitting exactly beneath it.
    duplicates = {
        anchor
        for fallback in root.iter(q("mc", "Fallback"))
        for anchor in fallback.iter(q("wp", "anchor"))
    }

    for index, anchor in enumerate(a for a in root.iter(q("wp", "anchor")) if a not in duplicates):
        kind, label = classify(anchor)
        position_h = anchor_position(anchor, "H")
        position_v = anchor_position(anchor, "V")
        element = {
            "id": f"element_{index + 1:03d}",
            "type": ELEMENT_TYPES[kind],
            "kind": kind,
            "label": label,
            "bounds": bounds(position_h, position_v, anchor_extent(anchor)),
            "rotation": 0,
            "zIndex": index,
            "visibility": anchor.get("behindDoc") != "1",
            "compatibility": COMPATIBILITY[kind],
            "warnings": element_warnings(kind, label, position_h, position_v),
        }
        buckets[section_of(anchor)].append(element)

    pages = [
        {
            "id": f"page_{i + 1:03d}",
            "index": i,
            "widthPt": size["widthPt"],
            "heightPt": size["heightPt"],
            "unit": "pt",
            "elements": elements,
        }
        for i, (size, elements) in enumerate(zip(sections, buckets, strict=True))
    ]
    return {
        "schemaVersion": "1.0",
        "source": {"type": "docx", "filename": filename, "sha256": source_sha},
        "document": {"pageCount": len(pages)},
        "pages": pages,
        "assets": {},
        "fonts": sorted(fonts(root)),
        "warnings": [],
    }


def element_warnings(
    kind: str, label: str, position_h: dict | None, position_v: dict | None
) -> list[dict]:
    if kind == "unsupported":
        return [
            warning(
                "unsupported_object",
                f"This {label} cannot be converted and is kept unchanged.",
                label=label,
            )
        ]
    if kind == "ink":
        return [warning("ink_removed", "A handwritten annotation was removed.")]
    if kind == "textbox" and not (position_h or position_v):
        return [
            warning(
                "textbox_unpositioned",
                "This text box has no usable position and will be placed inline.",
            )
        ]
    return []


def empty_manifest(filename: str, source_sha: str) -> dict:
    return {
        "schemaVersion": "1.0",
        "source": {"type": "docx", "filename": filename, "sha256": source_sha},
        "document": {"pageCount": 0},
        "pages": [],
        "assets": {},
        "fonts": [],
        "warnings": [warning("empty_document", "The document has no body content.")],
    }


def page_size(sect_pr: Element | None) -> dict:
    """Page dimensions in points. A4 unless the document says otherwise."""
    width, height = 11906, 16838
    if sect_pr is not None:
        size = sect_pr.find(q("w", "pgSz"))
        if size is not None:
            width = int(size.get(q("w", "w")) or width)
            height = int(size.get(q("w", "h")) or height)
    return {"widthPt": width / DXA_PER_POINT, "heightPt": height / DXA_PER_POINT}


def page_sizes(body: Element) -> list[dict]:
    found = [page_size(sect) for sect in body.iter(q("w", "sectPr"))]
    return found or [page_size(None)]


def section_index(body: Element, count: int):
    """Maps an anchor to the section it falls in, by document order.

    A <w:sectPr> inside a paragraph's properties *ends* a section, so anchors
    up to and including that paragraph belong to it.
    """
    order: dict[Element, int] = {}
    index = 0
    for child in body:
        for anchor in child.iter(q("wp", "anchor")):
            order[anchor] = index
        if child.find(q("w", "pPr") + "/" + q("w", "sectPr")) is not None:
            index += 1
    last = count - 1
    return lambda anchor: min(order.get(anchor, last), last)


def fonts(root: Element) -> set[str]:
    names = set()
    for element in root.iter(q("w", "rFonts")):
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            value = element.get(q("w", attr))
            if value:
                names.add(value)
    return names


# --------------------------------------------------------------------------
# Entry points, mirroring the PPTX preflight so the job path stays uniform
# --------------------------------------------------------------------------


def analyse(path: Path, output: Path, settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    package = Package(path, settings, DOCX)
    try:
        return _analyse(package, path, output)
    finally:
        package.close()


def _analyse(package: Package, path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    asset_dir = output / "assets"
    asset_dir.mkdir(exist_ok=True)

    source_sha = digest(path.read_bytes())
    manifest = parse(package, path.name, source_sha)

    assets: dict[str, dict] = {}
    for name in sorted(package.names):
        if not name.startswith("word/media/"):
            continue
        data = package.read(name)
        sha = digest(data)
        if sha in assets:
            assets[sha]["sourceParts"].append(name)
            continue
        target = "assets/" + sha  # generated name, never an archive path
        (output / target).write_bytes(data)
        mime = package.mime(name)
        assets[sha] = {
            "id": sha,
            "sha256": sha,
            "path": target,
            "mimeType": mime,
            "kind": mime.split("/", 1)[0]
            if mime.startswith(("image/", "audio/", "video/"))
            else "embedded",
            "byteLength": len(data),
            "sourceParts": [name],
            "status": "extracted",
        }
    manifest["assets"] = assets
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def analysis_report(manifest: dict) -> dict:
    counts = Counter(e["type"] for page in manifest["pages"] for e in page["elements"])
    warnings = list(manifest["warnings"])
    for page in manifest["pages"]:
        for element in page["elements"]:
            warnings.extend(
                {**w, "pageIndex": page["index"], "elementId": element["id"]}
                for w in element["warnings"]
            )
    return {
        "schemaVersion": "1.0",
        "status": "analysed",
        "sourceSha256": manifest["source"]["sha256"],
        "pages": len(manifest["pages"]),
        "dimensionsPt": {
            "width": manifest["pages"][0]["widthPt"] if manifest["pages"] else 0,
            "height": manifest["pages"][0]["heightPt"] if manifest["pages"] else 0,
        },
        "elementCounts": dict(counts),
        "assetCounts": dict(Counter(a["kind"] for a in manifest["assets"].values())),
        "fonts": manifest["fonts"],
        "warnings": warnings,
        "verification": "not_converted",
        "classificationBasis": "Preflight candidates, not verified Google compatibility.",
    }
