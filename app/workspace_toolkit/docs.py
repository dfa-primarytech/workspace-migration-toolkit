"""Google Docs renderer.

Takes a parsed DOCX package and produces a .docx that Google's importer turns
into a faithful Google Doc. It knows what Google accepts; it does not know why
Word wrote the source the way it did -- that is the parser's business.

Everything this module does is grounded in observed importer behaviour:

* **Floating tables are honoured.** A table with <w:tblpPr> lands where it is
  told, with text wrapping. So a floating text box becomes a floating table:
  editable text *and* original position, rather than a trade between them.
* **"Behind text" is honoured.** behindDoc="1" with wrapNone puts a picture
  under the text, which is what keeps a card's artwork while the text box
  floating above it stays readable.
* **Floating pictures are honoured**, so they are left exactly as they are.
* **Anchored text boxes are not** -- Google turns them into uneditable
  drawings. Those are the ones that must be rewritten.

Schema order matters in two places and breaks the file silently if ignored:
CT_TblPrBase requires tblpPr and tblOverlap before tblW, and CT_Anchor requires
any wrap element before <wp:docPr>.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

# Serialisation only; parsing always uses defusedxml.
from xml.etree.ElementTree import Element, SubElement, tostring  # nosec B405

from .docx import (
    COINCIDENT_SIZE_TOL,
    COINCIDENT_TOL_EMU,
    anchor_extent,
    anchor_position,
    classify,
    local,
    parents,
    q,
    to_dxa,
)
from .package import DOCX, Package

DEFAULT_WRAP_GAP_DXA = 180
WRAP_ELEMENTS = ("wrapNone", "wrapSquare", "wrapTight", "wrapThrough", "wrapTopAndBottom")
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'

# Text-bearing markers are deliberately not used to decide emptiness; see
# remove_empty_paragraphs.
PROPERTY_TAGS = {"pPr", "rPr"}


class Ids:
    """docPr ids must be unique within the document."""

    def __init__(self, start: int = 800001) -> None:
        self.value = start

    def next(self) -> int:
        self.value += 1
        return self.value


# --------------------------------------------------------------------------
# Passes
# --------------------------------------------------------------------------


def strip_fallbacks_keep_choice(root: Element) -> None:
    """Promotes mc:Choice and discards mc:Fallback.

    The fallback is a legacy VML restatement of the same shape. Keeping both
    would convert the content twice.
    """
    for container, alternate in _pairs(root, q("mc", "AlternateContent")):
        index = list(container).index(alternate)
        choice = alternate.find(q("mc", "Choice"))
        container.remove(alternate)
        if choice is None:
            continue
        for offset, child in enumerate(list(choice)):
            container.insert(index + offset, child)


def remove_ink_runs(root: Element) -> int:
    """Removes handwritten annotations, which are decorative and do not import."""
    removed = 0
    for container, run in _pairs(root, q("w", "r")):
        if run.find(".//" + q("w14", "contentPart")) is not None:
            container.remove(run)
            removed += 1
    return removed


def remove_background(root: Element) -> None:
    for container, background in _pairs(root, q("w", "background")):
        container.remove(background)


def replace_anchors(root: Element, ids: Ids) -> dict:
    """Rewrites floating content into constructs Google imports faithfully."""
    parent_of = parents(root)
    items = []
    for anchor in root.iter(q("wp", "anchor")):
        drawing = parent_of.get(anchor)
        if drawing is None:
            continue
        run = parent_of.get(drawing)
        kind, label = classify(anchor)
        items.append(
            {
                "anchor": anchor,
                "drawing": drawing,
                "run": run,
                "paragraph": _enclosing(parent_of, run, "p"),
                "kind": kind,
                "label": label,
                "h": anchor_position(anchor, "H"),
                "v": anchor_position(anchor, "V"),
                "extent": anchor_extent(anchor),
                "behind": False,
            }
        )

    _mark_backing_pictures(items)

    report = {"textboxes": 0, "pictures": 0, "ink": 0, "unsupported": {}}
    for item in items:
        kind = item["kind"]
        if kind == "unsupported":
            # Never delete what we cannot convert -- leave it for the importer.
            report["unsupported"][item["label"]] = report["unsupported"].get(item["label"], 0) + 1
        elif kind == "ink":
            _detach(parent_of, item["drawing"], item["anchor"])
            report["ink"] += 1
        elif kind == "picture":
            if item["behind"]:
                send_behind_text(item["anchor"])
            report["pictures"] += 1
        elif kind == "textbox":
            _replace_textbox(parent_of, item, ids)
            report["textboxes"] += 1
    return report


def _replace_textbox(parent_of: dict, item: dict, ids: Ids) -> None:
    paragraph = item["paragraph"]
    _detach(parent_of, item["drawing"], item["anchor"])
    if paragraph is None:
        return
    container = parent_of.get(paragraph)
    if container is None:
        return
    table = build_table(item, ids)
    if table is None:
        return
    at = list(container).index(paragraph) + 1
    # Adjacent <w:tbl> siblings merge into one table, so keep them apart.
    if at < len(container) and local(container[at].tag) == "tbl":
        container.insert(at, Element(q("w", "p")))
    container.insert(at, table)


def _mark_backing_pictures(items: list[dict]) -> None:
    """Finds pictures a text box is stacked on, and marks them to go behind.

    Word builds "card" layouts this way. A floating text box overlaps its
    backing picture rather than displacing it, so the artwork can stay -- but
    only if it is explicitly pushed behind the text, or it hides the box.
    """
    boxes = [i for i in items if i["kind"] == "textbox" and i["extent"] and i["h"] and i["v"]]
    for picture in items:
        if picture["kind"] != "picture" or not (
            picture["extent"] and picture["h"] and picture["v"]
        ):
            continue
        for box in boxes:
            if box["paragraph"] is not picture["paragraph"]:
                continue
            if not (_near(box["h"], picture["h"]) and _near(box["v"], picture["v"])):
                continue
            if _same_size(box["extent"], picture["extent"]):
                picture["behind"] = True
                break


def send_behind_text(anchor: Element) -> None:
    """Rewrites an anchor as "Behind text": behindDoc="1" plus wrapNone.

    The wrap element is replaced in place because CT_Anchor fixes the order of
    its children -- a wrap element after <wp:docPr> is invalid.
    """
    anchor.set("behindDoc", "1")
    at = None
    for name in WRAP_ELEMENTS:
        existing = anchor.find(q("wp", name))
        if existing is not None:
            at = list(anchor).index(existing)
            anchor.remove(existing)
            break
    if at is None:
        doc_pr = anchor.find(q("wp", "docPr"))
        at = list(anchor).index(doc_pr) if doc_pr is not None else len(anchor)
    anchor.insert(at, Element(q("wp", "wrapNone")))


def remove_empty_paragraphs(root: Element) -> None:
    """Removes paragraphs left hollow once their only content was relocated.

    Deliberately conservative. Listing "text bearing" tags instead loses
    fields, footnote and comment references, symbols, embedded objects and
    bookmarks -- all real content that simply is not <w:t>.
    """
    for container, paragraph in _pairs(root, q("w", "p")):
        properties = paragraph.find(q("w", "pPr"))
        # The final paragraph of a section carries sectPr: page size, margins
        # and orientation all live there.
        if properties is not None and properties.find(q("w", "sectPr")) is not None:
            continue
        # OOXML requires every <w:tc> to end with a paragraph.
        if local(container.tag) == "tc" and len(container.findall(q("w", "p"))) <= 1:
            continue
        # A paragraph wedged between two tables is what stops them merging.
        siblings = list(container)
        at = siblings.index(paragraph)
        if 0 < at < len(siblings) - 1:
            if local(siblings[at - 1].tag) == "tbl" and local(siblings[at + 1].tag) == "tbl":
                continue
        if not any(not _hollow(child) for child in paragraph):
            container.remove(paragraph)


def _hollow(element: Element) -> bool:
    name = local(element.tag)
    if name == "pPr":
        return True
    if name == "r":
        return all(local(child.tag) == "rPr" for child in element)
    return False


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def wrap_gap(anchor: Element, attribute: str) -> int:
    raw = anchor.get(attribute)
    try:
        return to_dxa(int(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WRAP_GAP_DXA


def floating_properties(item: dict) -> Element | None:
    """Builds <w:tblpPr> from the anchor's real coordinates.

    Returns None when neither axis gives a usable position, so the caller emits
    an ordinary inline table rather than a float anchored nowhere.
    """
    h, v = item["h"], item["v"]
    if not h and not v:
        return None
    anchor = item["anchor"]
    pr = Element(q("w", "tblpPr"))
    for name, attribute in (
        ("leftFromText", "distL"),
        ("rightFromText", "distR"),
        ("topFromText", "distT"),
        ("bottomFromText", "distB"),
    ):
        pr.set(q("w", name), str(wrap_gap(anchor, attribute)))

    # An axis with no usable position borrows the other's frame, so the table
    # is never anchored to two different coordinate systems at once.
    pr.set(q("w", "horzAnchor"), (h or v)["frame"])
    pr.set(q("w", "vertAnchor"), (v or h)["frame"])
    _axis(pr, h, "tblpX", "tblpXSpec")
    _axis(pr, v, "tblpY", "tblpYSpec")
    return pr


def _axis(pr: Element, position: dict | None, offset_attr: str, spec_attr: str) -> None:
    if position and position["mode"] == "offset":
        pr.set(q("w", offset_attr), str(to_dxa(position["emu"])))
    elif position and position["mode"] == "align":
        pr.set(q("w", spec_attr), position["align"])
    else:
        pr.set(q("w", offset_attr), "0")


def build_table(item: dict, ids: Ids) -> Element | None:
    content = item["anchor"].find(".//" + q("w", "txbxContent"))
    if content is None:
        return None
    width = to_dxa(item["extent"]["cx"]) if item["extent"] else 9000

    table = Element(q("w", "tbl"))
    properties = SubElement(table, q("w", "tblPr"))

    # Schema order: tblpPr and tblOverlap must precede tblW.
    position = floating_properties(item)
    if position is not None:
        properties.append(position)
        SubElement(properties, q("w", "tblOverlap")).set(q("w", "val"), "never")

    SubElement(properties, q("w", "tblW")).attrib.update(
        {q("w", "w"): str(width), q("w", "type"): "dxa"}
    )
    borders = SubElement(properties, q("w", "tblBorders"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        SubElement(borders, q("w", side)).attrib.update(
            {
                q("w", "val"): "none",
                q("w", "sz"): "0",
                q("w", "space"): "0",
                q("w", "color"): "auto",
            }
        )
    SubElement(properties, q("w", "tblLook")).set(q("w", "val"), "0000")

    grid = SubElement(table, q("w", "tblGrid"))
    SubElement(grid, q("w", "gridCol")).set(q("w", "w"), str(width))

    row = SubElement(table, q("w", "tr"))
    row.append(build_cell(item, content, width))
    _ = ids  # docPr ids are only needed when rebuilding drawings
    return table


def build_cell(item: dict, content: Element, width: int) -> Element:
    cell = Element(q("w", "tc"))
    properties = SubElement(cell, q("w", "tcPr"))
    SubElement(properties, q("w", "tcW")).attrib.update(
        {q("w", "w"): str(width), q("w", "type"): "dxa"}
    )
    fill = shape_fill(item["anchor"])
    if fill:
        SubElement(properties, q("w", "shd")).attrib.update(
            {q("w", "val"): "clear", q("w", "color"): "auto", q("w", "fill"): fill}
        )
    margins = SubElement(properties, q("w", "tcMar"))
    for side in ("top", "left", "bottom", "right"):
        SubElement(margins, q("w", side)).attrib.update({q("w", "w"): "120", q("w", "type"): "dxa"})
    SubElement(properties, q("w", "vAlign")).set(q("w", "val"), "center")

    # Move the original paragraphs verbatim rather than rebuilding them: all
    # their formatting, runs and inline images come along untouched.
    for paragraph in list(content):
        content.remove(paragraph)
        cell.append(paragraph)
    if cell.find(q("w", "p")) is None:
        SubElement(cell, q("w", "p"))
    return cell


def shape_fill(anchor: Element) -> str | None:
    properties = anchor.find(".//" + q("wps", "spPr"))
    if properties is None or properties.find(".//" + q("a", "noFill")) is not None:
        return None
    solid = properties.find(q("a", "solidFill"))
    if solid is None:
        return None
    colour = solid.find(q("a", "srgbClr"))
    return colour.get("val") if colour is not None else None


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def transform(root: Element, ids: Ids | None = None) -> dict:
    """Applies every pass, in the order they depend on each other."""
    ids = ids or Ids()
    strip_fallbacks_keep_choice(root)
    # Ink runs go first, so replace_anchors never sees them -- which is why the
    # count is carried across rather than taken from that pass.
    ink = remove_ink_runs(root)
    remove_background(root)
    report = replace_anchors(root, ids)
    report["ink"] += ink
    remove_empty_paragraphs(root)
    return report


def serialise(root: Element) -> bytes:
    return XML_DECLARATION + tostring(root, encoding="utf-8", xml_declaration=False)


def render(package: Package, destination: Path) -> dict:
    """Writes a Google-ready .docx beside the original and reports what changed."""
    root = package.xml(DOCX.main_part)
    report = transform(root)
    document = serialise(root)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
        for name in sorted(package.names):
            data = document if name == DOCX.main_part else package.read(name)
            out.writestr(name, data)
    return report


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _pairs(root: Element, tag: str) -> list[tuple[Element, Element]]:
    """(parent, child) pairs for every matching element, safe to mutate over."""
    parent_of = parents(root)
    return [(parent_of[e], e) for e in root.iter(tag) if e in parent_of]


def _enclosing(parent_of: dict, element: Element | None, name: str) -> Element | None:
    while element is not None and local(element.tag) != name:
        element = parent_of.get(element)
    return element


def _detach(parent_of: dict, drawing: Element, anchor: Element) -> None:
    if anchor in list(drawing):
        drawing.remove(anchor)


def _near(a: dict, b: dict) -> bool:
    if a["mode"] != "offset" or b["mode"] != "offset":
        return a == b
    return abs(a["emu"] - b["emu"]) <= COINCIDENT_TOL_EMU


def _same_size(a: dict, b: dict) -> bool:
    return (
        abs(a["cx"] - b["cx"]) / max(a["cx"], 1) <= COINCIDENT_SIZE_TOL
        and abs(a["cy"] - b["cy"]) / max(a["cy"], 1) <= COINCIDENT_SIZE_TOL
    )
