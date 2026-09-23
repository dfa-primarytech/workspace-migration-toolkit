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
CT_TblPrBase requires tblpPr, tblOverlap and bidiVisual before tblW, and
CT_Anchor requires any wrap element before <wp:docPr>.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Serialisation only; parsing always uses defusedxml.
from xml.etree.ElementTree import Element, SubElement, tostring  # nosec B405

from .docx import (
    COINCIDENT_SIZE_TOL,
    COINCIDENT_TOL_EMU,
    OFF_VALUES,
    analysis_report,
    anchor_extent,
    anchor_position,
    classify,
    local,
    parents,
    q,
    to_dxa,
)
from .errors import ToolkitError
from .model import Compatibility as C
from .model import warning
from .package import DOCX, Package

DEFAULT_WRAP_GAP_DXA = 180
WRAP_ELEMENTS = ("wrapNone", "wrapSquare", "wrapTight", "wrapThrough", "wrapTopAndBottom")
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'

# Text-bearing markers are deliberately not used to decide emptiness; see
# remove_empty_paragraphs.
PROPERTY_TAGS = {"pPr", "rPr"}


@dataclass
class Anchored:
    """One floating object, with everything the passes need to decide about it.

    A dataclass rather than a dict because the fields are heterogeneous and
    every consumer indexes them; typing this as a mapping loses all of that.
    """

    anchor: Element
    drawing: Element
    run: Element | None
    paragraph: Element | None
    kind: str
    label: str
    h: dict | None
    v: dict | None
    extent: dict | None
    behind: bool = field(default=False)


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
    items: list[Anchored] = []
    for anchor in root.iter(q("wp", "anchor")):
        drawing = parent_of.get(anchor)
        if drawing is None:
            continue
        run = parent_of.get(drawing)
        kind, label = classify(anchor)
        items.append(
            Anchored(
                anchor=anchor,
                drawing=drawing,
                run=run,
                paragraph=_enclosing(parent_of, run, "p"),
                kind=kind,
                label=label,
                h=anchor_position(anchor, "H"),
                v=anchor_position(anchor, "V"),
                extent=anchor_extent(anchor),
            )
        )

    _mark_backing_pictures(items)

    unsupported: dict[str, int] = {}
    report: dict[str, Any] = {
        "textboxes": 0,
        "pictures": 0,
        "ink": 0,
        "unsupported": unsupported,
    }
    for item in items:
        if item.kind == "unsupported":
            # Never delete what we cannot convert -- leave it for the importer.
            unsupported[item.label] = unsupported.get(item.label, 0) + 1
        elif item.kind == "ink":
            _detach(item.drawing, item.anchor)
            report["ink"] += 1
        elif item.kind == "picture":
            if item.behind:
                send_behind_text(item.anchor)
            report["pictures"] += 1
        elif item.kind == "textbox":
            _replace_textbox(parent_of, item, ids)
            report["textboxes"] += 1
    return report


def _replace_textbox(parent_of: dict, item: Anchored, ids: Ids) -> None:
    paragraph = item.paragraph
    _detach(item.drawing, item.anchor)
    if paragraph is None:
        return
    container = parent_of.get(paragraph)
    if container is None:
        return
    table = build_table(item, ids)
    if table is None:
        return
    index = list(container).index(paragraph)
    # A paragraph carrying <w:sectPr> *ends* its section. Inserting after it
    # would push the table into the next section, where a different page size,
    # orientation and set of margins apply -- so portrait content can end up
    # laid out landscape. Content belonging to this section must precede it.
    at = index if _ends_section(paragraph) else index + 1
    container.insert(at, table)
    _keep_tables_apart(container, at, rtl=is_rtl(paragraph))


def _ends_section(paragraph: Element) -> bool:
    properties = paragraph.find(q("w", "pPr"))
    return properties is not None and properties.find(q("w", "sectPr")) is not None


def stated_direction(paragraph: Element | None) -> bool | None:
    """True if this paragraph says right to left, False if it says left to
    right, None if it does not say.

    The three-way answer is the point. `<w:bidi w:val="0"/>` is an author
    turning direction *off* for this paragraph, which is a different fact from
    a paragraph that simply never mentions direction -- and the two have to
    lead to different decisions, or an explicit override gets ignored.

    Only the paragraph's own `pPr` is read. Direction inherited from a
    paragraph style in styles.xml is **not** resolved, so a paragraph that
    reads right to left purely by style reports None here.
    """
    if paragraph is None:
        return None
    properties = paragraph.find(q("w", "pPr"))
    if properties is None:
        return None
    bidi = properties.find(q("w", "bidi"))
    if bidi is None:
        return None
    return bidi.get(q("w", "val")) not in OFF_VALUES


def is_rtl(paragraph: Element | None) -> bool:
    """Whether this paragraph states that it reads right to left.

    A paragraph that says nothing is treated as left to right, which is the
    OOXML default.
    """
    return stated_direction(paragraph) is True


def box_direction(content: Element, anchored_to: Element | None) -> bool:
    """The direction a converted text box should be given.

    The box's own paragraphs are the authority: the first one that states a
    direction decides, including when it states left to right. Only when no
    paragraph in the box says anything -- an empty box, or one whose direction
    comes from a style we do not resolve -- does the paragraph it is anchored
    to get a say.

    Known limits, stated rather than papered over:

    * A box whose paragraphs **disagree** is given the first stated direction.
      There is one table and one direction to put on it, so a mixed box cannot
      be represented faithfully either way.
    * Direction inherited from a paragraph style is invisible here, so such a
      box falls through to its anchor.
    """
    for paragraph in content.findall(".//" + q("w", "p")):
        stated = stated_direction(paragraph)
        if stated is not None:
            return stated
    return stated_direction(anchored_to) is True


def new_paragraph(rtl: bool = False) -> Element:
    """An empty paragraph, reading the same way as the text around it.

    Every paragraph this converter *creates* -- table separators, the filler
    an empty cell requires -- has no author to inherit direction from. Left
    bare in a right-to-left document it reads left to right, which puts the
    paragraph mark and the caret on the wrong side of the page.
    """
    paragraph = Element(q("w", "p"))
    if rtl:
        SubElement(SubElement(paragraph, q("w", "pPr")), q("w", "bidi"))
    return paragraph


def _keep_tables_apart(container: Element, at: int, rtl: bool = False) -> None:
    """Adjacent <w:tbl> siblings merge into one table, so separate them."""
    children = list(container)
    if at + 1 < len(children) and local(children[at + 1].tag) == "tbl":
        container.insert(at + 1, new_paragraph(rtl))
    if at > 0 and local(children[at - 1].tag) == "tbl":
        container.insert(at, new_paragraph(rtl))


def _mark_backing_pictures(items: list[Anchored]) -> None:
    """Finds pictures a text box is stacked on, and marks them to go behind.

    Word builds "card" layouts this way. A floating text box overlaps its
    backing picture rather than displacing it, so the artwork can stay -- but
    only if it is explicitly pushed behind the text, or it hides the box.
    """
    boxes = [i for i in items if i.kind == "textbox" and i.extent and i.h and i.v]
    for picture in items:
        if picture.kind != "picture" or not (picture.extent and picture.h and picture.v):
            continue
        for box in boxes:
            if box.paragraph is not picture.paragraph:
                continue
            if not (_near(box.h, picture.h) and _near(box.v, picture.v)):
                continue
            if box.extent and _same_size(box.extent, picture.extent):
                picture.behind = True
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


# VML style lengths carry their unit. Word writes pt almost always, but not
# only -- and a picture skipped for an unrecognised unit is a picture lost.
VML_UNITS_TO_EMU = {
    "pt": 12700,
    "in": 914400,
    "cm": 360000,
    "mm": 36000,
    "pc": 152400,
    "px": 9525,  # at VML's assumed 96dpi
}
VML_LENGTH = re.compile(r"(-?[\d.]+)\s*(pt|in|cm|mm|pc|px)", re.IGNORECASE)


def vml_length(style: str, name: str) -> int | None:
    """Reads one dimension out of a VML style attribute, in EMU."""
    match = re.search(name + r"\s*:\s*([^;]+)", style, re.IGNORECASE)
    if not match:
        return None
    size = VML_LENGTH.match(match.group(1).strip())
    if not size:
        return None
    try:
        return round(float(size.group(1)) * VML_UNITS_TO_EMU[size.group(2).lower()])
    except (ValueError, KeyError):
        return None


def fix_legacy_pictures(root: Element, ids: Ids) -> int:
    """Rewrites VML-only pictures as modern inline DrawingML.

    Word keeps some images as <w:pict> with a VML shape and no DrawingML
    sibling -- usually pasted or very old content. Google's importer ignores
    them entirely, so the picture simply disappears. Rebuilding them as an
    inline <w:drawing> referencing the same relationship keeps the image.

    Only touches a <w:pict> whose parent is a run: it also appears inside
    <w:object>, where a <w:drawing> is not a legal child.
    """
    converted = 0
    for container, pict in _pairs(root, q("w", "pict")):
        if local(container.tag) != "r":
            continue
        shape = pict.find(".//" + q("v", "shape"))
        image = pict.find(".//" + q("v", "imagedata"))
        if shape is None or image is None:
            continue
        rid = image.get(q("r", "id"))
        if not rid:
            continue
        style = shape.get("style") or ""
        cx = vml_length(style, "width")
        cy = vml_length(style, "height")
        if not cx or not cy:
            continue
        at = list(container).index(pict)
        container.remove(pict)
        container.insert(at, make_inline_drawing(rid, cx, cy, shape.get("alt") or "Picture", ids))
        converted += 1
    return converted


def make_inline_drawing(rid: str, cx: int, cy: int, name: str, ids: Ids) -> Element:
    """Builds the <w:drawing> wrapper for an inline picture."""
    number = str(ids.next())
    drawing = Element(q("w", "drawing"))
    inline = SubElement(drawing, q("wp", "inline"))
    inline.attrib.update({"distT": "0", "distB": "0", "distL": "0", "distR": "0"})
    SubElement(inline, q("wp", "extent")).attrib.update({"cx": str(cx), "cy": str(cy)})
    SubElement(inline, q("wp", "effectExtent")).attrib.update(
        {"l": "0", "t": "0", "r": "0", "b": "0"}
    )
    SubElement(inline, q("wp", "docPr")).attrib.update({"id": number, "name": name})
    frame = SubElement(inline, q("wp", "cNvGraphicFramePr"))
    SubElement(frame, q("a", "graphicFrameLocks")).set("noChangeAspect", "1")

    graphic = SubElement(inline, q("a", "graphic"))
    data = SubElement(graphic, q("a", "graphicData"))
    data.set("uri", "http://schemas.openxmlformats.org/drawingml/2006/picture")
    picture = SubElement(data, q("pic", "pic"))
    properties = SubElement(picture, q("pic", "nvPicPr"))
    SubElement(properties, q("pic", "cNvPr")).attrib.update({"id": number, "name": name})
    SubElement(properties, q("pic", "cNvPicPr"))
    fill = SubElement(picture, q("pic", "blipFill"))
    SubElement(fill, q("a", "blip")).set(q("r", "embed"), rid)
    SubElement(SubElement(fill, q("a", "stretch")), q("a", "fillRect"))
    shape_properties = SubElement(picture, q("pic", "spPr"))
    transform_element = SubElement(shape_properties, q("a", "xfrm"))
    SubElement(transform_element, q("a", "off")).attrib.update({"x": "0", "y": "0"})
    SubElement(transform_element, q("a", "ext")).attrib.update({"cx": str(cx), "cy": str(cy)})
    geometry = SubElement(shape_properties, q("a", "prstGeom"))
    geometry.set("prst", "rect")
    SubElement(geometry, q("a", "avLst"))
    return drawing


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


def floating_properties(item: Anchored) -> Element | None:
    """Builds <w:tblpPr> from the anchor's real coordinates.

    Returns None when neither axis gives a usable position, so the caller emits
    an ordinary inline table rather than a float anchored nowhere.
    """
    h, v = item.h, item.v
    if not h and not v:
        return None
    anchor = item.anchor
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
    # One of the two is always set; the guard above returned otherwise.
    horizontal, vertical = h or v, v or h
    pr.set(q("w", "horzAnchor"), horizontal["frame"] if horizontal else "text")
    pr.set(q("w", "vertAnchor"), vertical["frame"] if vertical else "text")
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


def build_table(item: Anchored, ids: Ids) -> Element | None:
    content = item.anchor.find(".//" + q("w", "txbxContent"))
    if content is None:
        return None
    width = to_dxa(item.extent["cx"]) if item.extent else 9000
    rtl = box_direction(content, item.paragraph)

    table = Element(q("w", "tbl"))
    properties = SubElement(table, q("w", "tblPr"))

    # Schema order: CT_TblPrBase runs tblpPr, tblOverlap, bidiVisual, then
    # tblW. Emitting bidiVisual after tblW would be rejected by a validating
    # reader even though every element is individually correct.
    position = floating_properties(item)
    if position is not None:
        properties.append(position)
        SubElement(properties, q("w", "tblOverlap")).set(q("w", "val"), "never")

    # A right-to-left text box becomes a right-to-left table. With one column
    # there is no cell order to mirror, so this changes nothing visible today
    # -- it states the table's direction so that a reader laying out borders,
    # indentation or any future multi-column cell does not have to guess.
    if rtl:
        SubElement(properties, q("w", "bidiVisual"))

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
    row.append(build_cell(item, content, width, rtl=rtl))
    _ = ids  # docPr ids are only needed when rebuilding drawings
    return table


def build_cell(item: Anchored, content: Element, width: int, rtl: bool = False) -> Element:
    cell = Element(q("w", "tc"))
    properties = SubElement(cell, q("w", "tcPr"))
    SubElement(properties, q("w", "tcW")).attrib.update(
        {q("w", "w"): str(width), q("w", "type"): "dxa"}
    )
    fill = shape_fill(item.anchor)
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
        # OOXML requires a cell to end with a paragraph. This one is ours, so
        # it has no author's direction to inherit.
        cell.append(new_paragraph(rtl))
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
    # After the anchors: a legacy picture inside a text box only becomes
    # reachable once that text box has been moved into its table.
    report["legacyPictures"] = fix_legacy_pictures(root, ids)
    remove_empty_paragraphs(root)
    return report


def serialise(root: Element) -> bytes:
    return XML_DECLARATION + tostring(root, encoding="utf-8", xml_declaration=False)


HEADER_FOOTER = re.compile(r"^word/(header|footer)\d*\.xml$")


def story_parts(package: Package) -> list[str]:
    """Every part carrying body-like content, not just the main document.

    Headers and footers hold exactly the same constructs -- anchored text
    boxes, legacy pictures, ink -- and Google mishandles them the same way.
    Leaving them out means branded letterheads and title blocks break while the
    body converts cleanly.
    """
    headers = sorted(n for n in package.names if HEADER_FOOTER.match(n))
    return [DOCX.main_part, *headers]


def render(package: Package, destination: Path) -> dict:
    """Writes a Google-ready .docx beside the original and reports what changed."""
    ids = Ids()
    report: dict[str, Any] = {
        "textboxes": 0,
        "pictures": 0,
        "ink": 0,
        "legacyPictures": 0,
        "equations": 0,
        "regeneratedFields": 0,
        "unsupported": {},
        "parts": [],
    }
    rewritten: dict[str, bytes] = {}
    tokens: Counter = Counter()

    for name in story_parts(package):
        root = package.xml(name)
        if name == DOCX.main_part:
            # Body text only. Drive's plain-text export does not reliably
            # include headers, so counting them would invent mismatches.
            tokens = Counter(source_text(root).split())
        part_report = transform(root, ids)
        # Every part, unlike the token comparison above: that is body-only
        # because comparing header text would invent mismatches, which says
        # nothing about where an equation can be. An equation in a letterhead
        # is as unverified as one in the body.
        #
        # Counted after the transform, so a construct restated inside
        # mc:Fallback is counted once rather than twice.
        report["equations"] += count_equations(root)
        report["regeneratedFields"] += count_regenerated_fields(root)
        rewritten[name] = serialise(root)
        report["parts"].append(name)
        for key in ("textboxes", "pictures", "ink", "legacyPictures"):
            report[key] += part_report[key]
        for label, count in part_report["unsupported"].items():
            report["unsupported"][label] = report["unsupported"].get(label, 0) + count

    report["tokens"] = dict(tokens)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
        for name in sorted(package.names):
            out.writestr(name, rewritten.get(name) or package.read(name))
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


def _detach(drawing: Element, anchor: Element) -> None:
    """Removes the anchor, deliberately leaving `<w:r><w:drawing/></w:r>` behind.

    The empty wrapper is kept because removing it buys nothing: rendering the
    same converted document with and without the leftovers puts the text in
    exactly the same place, measured against LibreOffice in
    test_docx_validity.py. Issue #20 was closed on that evidence.

    It does have one consequence worth knowing before reasoning about
    remove_empty_paragraphs. A run holding an empty drawing is not `_hollow`,
    so the paragraph around it is never a candidate for removal at all --
    whatever else is or is not protecting it. A test written on the assumption
    that some guard was keeping that paragraph alive would pass with the guard
    deleted, because the paragraph was never at risk. One in #18 did exactly
    that.
    """
    if anchor in list(drawing):
        drawing.remove(anchor)


def _near(a: dict | None, b: dict | None) -> bool:
    if a is None or b is None:
        return False
    if a["mode"] != "offset" or b["mode"] != "offset":
        return a == b
    return abs(a["emu"] - b["emu"]) <= COINCIDENT_TOL_EMU


def _same_size(a: dict, b: dict) -> bool:
    return (
        abs(a["cx"] - b["cx"]) / max(a["cx"], 1) <= COINCIDENT_SIZE_TOL
        and abs(a["cy"] - b["cy"]) / max(a["cy"], 1) <= COINCIDENT_SIZE_TOL
    )


# Fields whose displayed value is computed from page layout or the clock
# rather than authored. What any particular reader does with them after an
# import -- recalculate, leave the cached value stale, or flatten the field to
# plain text -- is not something this converter knows, so the cached value is
# not treated as text it was responsible for carrying across.
REGENERATED_FIELDS = {
    "TOC",
    "TOA",
    "INDEX",
    "PAGE",
    "NUMPAGES",
    "SECTIONPAGES",
    "PAGEREF",
    "SEQ",
    "STYLEREF",
    "DATE",
    "TIME",
    "CREATEDATE",
    "SAVEDATE",
    "PRINTDATE",
    "REVNUM",
}


def field_name(instruction: str) -> str:
    """The field's type, from the start of its instruction text."""
    stripped = instruction.strip().lstrip("\\").strip()
    return stripped.split(" ", 1)[0].upper() if stripped else ""


def _regenerated(instruction: str) -> bool:
    return field_name(instruction) in REGENERATED_FIELDS


def _cached_result_text(root: Element) -> set[int]:
    """Identifies `<w:t>` nodes holding the cached result of a computed field.

    Word stores what a field *displayed* when it was last updated, between
    `fldChar separate` and `fldChar end`, or inside `<w:fldSimple>`. For a
    table of contents that cache is the entry text and its page numbers.
    """
    skip: set[int] = set()

    for simple in root.iter(q("w", "fldSimple")):
        if _regenerated(simple.get(q("w", "instr")) or ""):
            skip.update(id(node) for node in simple.iter(q("w", "t")))

    # Complex fields are a flat run of markers, not a subtree, so they need a
    # state machine rather than a containment test. They nest: a PAGEREF sits
    # inside the TOC result, and its own end marker must not close the TOC.
    stack: list[dict[str, Any]] = []
    for node in root.iter():
        tag = local(node.tag)
        if tag == "fldChar":
            kind = node.get(q("w", "fldCharType"))
            if kind == "begin":
                stack.append({"instruction": "", "in_result": False})
            elif kind == "separate" and stack:
                stack[-1]["in_result"] = True
            elif kind == "end" and stack:
                stack.pop()
        elif tag == "instrText" and stack:
            stack[-1]["instruction"] += node.text or ""
        elif tag == "t" and any(f["in_result"] and _regenerated(f["instruction"]) for f in stack):
            skip.add(id(node))
    return skip


def source_text(root: Element) -> str:
    """All body text, used only to check nothing vanished during import.

    Two deliberate omissions, for opposite reasons.

    Equation text is `<m:t>`, not `<w:t>`, so it never appeared here at all;
    see count_equations.

    The cached result of a computed field *is* `<w:t>` and did appear, which
    was worse. A table of contents caches its entries and page numbers as
    ordinary text. Those values depend on pagination, so a reader that lays the
    document out differently may show different ones -- and a reader that does
    not recalculate may show the old ones. Either way the comparison cannot
    tell a renumbered contents page from a lost one, so counting them produced
    a missing-text report per entry on documents that had lost nothing.

    The field instruction is preserved either way; what is dropped here is only
    the stale answer, not the question.
    """
    skip = _cached_result_text(root)
    return " ".join((node.text or "") for node in root.iter(q("w", "t")) if id(node) not in skip)


def count_regenerated_fields(root: Element) -> int:
    """Fields whose displayed value is computed rather than authored."""
    total = sum(
        1 for s in root.iter(q("w", "fldSimple")) if _regenerated(s.get(q("w", "instr")) or "")
    )
    stack: list[str] = []
    for node in root.iter():
        tag = local(node.tag)
        if tag == "fldChar":
            kind = node.get(q("w", "fldCharType"))
            if kind == "begin":
                stack.append("")
            elif kind == "end" and stack:
                if _regenerated(stack.pop()):
                    total += 1
        elif tag == "instrText" and stack:
            stack[-1] += node.text or ""
    return total


def count_equations(root: Element) -> int:
    """How many equations this part contains.

    Equation text is `<m:t>`, so it is not in the token comparison and a lost
    equation would not show up as missing text. Folding it in is not the
    answer: whether Drive's plain-text export includes equation content is
    unknown, and if it does not, every maths document would report text it
    never lost. The same reasoning already keeps headers out of that count.

    So equations are counted and reported as unverified instead. They are not
    the only content the text check cannot speak for -- layout is the standing
    example -- but they are content a reader can be pointed at directly.
    """
    return sum(1 for _ in root.iter(q("m", "oMath")))


def render_path(source: Path, destination: Path, settings) -> dict:
    """Opens the package through the same guards and renders it."""
    package = Package(source, settings, DOCX)
    try:
        return render(package, destination)
    finally:
        package.close()


def verify(
    tokens: dict, exported: str, equations: int = 0, regenerated_fields: int = 0
) -> list[dict]:
    """Compares the converted document's text against the source's.

    A whitespace-normalised token multiset catches text that went missing or
    got duplicated, and reports only counts -- never the text itself, which
    would put document content into a report saved to Drive.

    This says nothing about layout. Positioning is exactly what cannot be
    checked without human eyes, which is why the review warning is
    unconditional.
    """
    findings = []
    missing = Counter(tokens) - Counter(exported.split())
    if missing:
        findings.append(
            warning(
                "text_mismatch",
                "Some source text could not be verified after import.",
                missingTokenCount=sum(missing.values()),
                classification=C.UNSUPPORTED,
            )
        )
    if equations:
        findings.append(
            warning(
                "equations_not_verified",
                "This document contains equations. They were passed through "
                "unchanged, but whether they survived the import has not been "
                "checked automatically -- open the document and confirm.",
                equationCount=equations,
                classification=C.UNSUPPORTED,
            )
        )
    if regenerated_fields:
        findings.append(
            warning(
                "fields_need_regeneration",
                "This document contains fields whose displayed values -- table "
                "of contents entries, page numbers, dates -- are calculated "
                "from page layout or the date rather than typed in. After "
                "import they may be recalculated, or may still show the old "
                "values. Open the contents page and any page numbering and "
                "check them rather than assuming they carried across.",
                fieldCount=regenerated_fields,
                classification=C.SUBSTITUTED,
            )
        )
    findings.append(
        warning(
            "visual_review_required",
            "Check the position of text boxes, images and tables in the converted "
            "document. Layout has not been verified automatically.",
            classification=C.UNSUPPORTED,
        )
    )
    return findings


async def convert(
    root: Path,
    manifest: dict,
    google,
    progress: dict | None = None,
    output_name: str = "Converted document",
) -> dict:
    """Uploads the rendered .docx for native import, then checks what came back."""
    from .google import DOCS_MIME, DRIVE  # imported here to avoid a cycle

    report = progress if progress is not None else {}
    report.update(analysis_report(manifest))
    report.update(status="converting", outputs=[], assetOutputs=[])
    result = root / "result"
    try:
        formats = await google.request("GET", DRIVE + "/about", params={"fields": "importFormats"})
        if DOCS_MIME not in formats.get("importFormats", {}).get(DOCX.mime, []):
            raise ToolkitError(
                "conversion_unavailable",
                "Google does not currently offer Word conversion for this account.",
                422,
            )
        folder = await google.folder()
        report["folderUrl"] = "https://drive.google.com/drive/folders/" + folder

        # The repaired package, not the original: the repairs are the point.
        uploaded = await google.upload(
            result / "converted.docx",
            output_name,
            DOCX.mime,
            folder,
            convert=True,
            target=DOCS_MIME,
        )
        report["outputs"].append({"kind": "document", "id": uploaded["id"]})
        report["documentId"] = uploaded["id"]
        report["url"] = "https://docs.google.com/document/d/" + uploaded["id"] + "/edit"

        # Keep every extracted asset privately alongside the document, so
        # anything the importer drops is still recoverable by hand.
        for asset in manifest["assets"].values():
            saved = await google.upload(
                result / asset["path"], asset["id"], asset["mimeType"], folder
            )
            report["assetOutputs"].append(
                {
                    "assetId": asset["id"],
                    "kind": asset["kind"],
                    "driveFileId": saved["id"],
                    "url": "https://drive.google.com/file/d/" + saved["id"] + "/view",
                }
            )

        render_report = json.loads((result / "render.json").read_text(encoding="utf-8"))
        exported = await google.export_text(uploaded["id"])
        report["warnings"].extend(
            verify(
                render_report.get("tokens", {}),
                exported,
                equations=render_report.get("equations", 0),
                regenerated_fields=render_report.get("regeneratedFields", 0),
            )
        )
        report["conversion"] = {
            k: v
            for k, v in render_report.items()
            if k in {"textboxes", "pictures", "ink", "equations", "regeneratedFields"}
        }
        report["conversion"]["unsupportedKept"] = render_report.get("unsupported", {})
        report["verification"] = "text_checked"
        report["status"] = "completed_with_warnings"
    except ToolkitError as exc:
        report["status"] = "failed_with_partial_outputs" if report.get("folderUrl") else "failed"
        report["warnings"].append(warning(exc.code, exc.message, classification=C.UNSUPPORTED))
        report["verification"] = "incomplete"

    if report.get("folderUrl"):
        path = root / "conversion-report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        try:
            saved = await google.upload(
                path,
                "Conversion report.json",
                "application/json",
                report["folderUrl"].rsplit("/", 1)[-1],
            )
            report["reportUrl"] = "https://drive.google.com/file/d/" + saved["id"] + "/view"
        except ToolkitError:
            report["warnings"].append(
                warning(
                    "report_upload_failed",
                    "The report could not be saved to Drive. Download it from this page.",
                )
            )
    return report
