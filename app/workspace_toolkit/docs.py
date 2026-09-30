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
    EXTENSION_NS,
    MARGIN_AREAS,
    NS,
    OFF_VALUES,
    STYLES_PART,
    THEME_PART,
    analysis_report,
    anchor_extent,
    anchor_position,
    body_blocks,
    classify,
    font_requirements,
    governing_sections,
    local,
    margin_area,
    page_geometry,
    parents,
    q,
    section_of,
    to_dxa,
    twips,
)
from .errors import ToolkitError
from .model import UNCOMPARABLE, text_tokens, warning
from .model import Compatibility as C
from .package import DOCX, Package
from .readback import read_back

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


def replace_anchors(root: Element, ids: Ids, fallback: Element | None = None) -> dict:
    """Rewrites floating content into constructs Google imports faithfully."""
    parent_of = parents(root)
    sections = Sections(root, parent_of, fallback)
    items: list[Anchored] = []
    for anchor in root.iter(q("wp", "anchor")):
        drawing = parent_of.get(anchor)
        if drawing is None:
            continue
        run = parent_of.get(drawing)
        kind, label = classify(anchor)
        geometry = page_geometry(sections.of(anchor))
        items.append(
            Anchored(
                anchor=anchor,
                drawing=drawing,
                run=run,
                paragraph=_enclosing(parent_of, run, "p"),
                kind=kind,
                label=label,
                h=anchor_position(anchor, "H", geometry),
                v=anchor_position(anchor, "V", geometry),
                extent=anchor_extent(anchor),
            )
        )

    _mark_backing_pictures(items)

    unsupported: dict[str, int] = {}
    report: dict[str, Any] = {
        "textboxes": 0,
        "pictures": 0,
        "picturesInlined": 0,
        "ink": 0,
        "unsupported": unsupported,
        # Placed by the inside or outside margin, which is on one side on odd
        # pages and the other on even ones: kept where it always went, and
        # counted so a person knows to check it (#112).
        "positionsPageSideUncertain": sum(
            1
            for item in items
            if item.kind in ("textbox", "picture")
            and any(axis and axis.get("uncertain") for axis in (item.h, item.v))
        ),
    }
    for item in items:
        if item.kind == "unsupported":
            # Never delete what we cannot convert -- leave it for the importer.
            unsupported[item.label] = unsupported.get(item.label, 0) + 1
        elif item.kind == "ink":
            _detach(item.drawing, item.anchor)
            report["ink"] += 1
        elif item.kind == "textbox":
            # Counted only when a table was actually produced. A report saying
            # four text boxes were converted, when four empty boxes were
            # skipped, describes work that did not happen.
            if _replace_textbox(parent_of, item, ids):
                report["textboxes"] += 1
    # Pictures last, against the tree as the text boxes left it: a picture
    # floating inside a box has just moved into the cell the box became, and
    # the map taken before would still place it in the box, not the cell (#146).
    parent_of = parents(root)
    for item in items:
        if item.kind == "picture":
            if item.behind:
                send_behind_text(item.anchor)
            elif _inline_picture(parent_of, item, ids):
                report["picturesInlined"] += 1
            report["pictures"] += 1
    return report


def _inline_picture(parent_of: dict, item: Anchored, ids: Ids) -> bool:
    """Turns a picture floating inside a table cell into inline cell content.

    A floating picture is positioned against the page, the margin or a
    paragraph -- never against the cell it sits in. So the cell allocates no
    height for it, the row stays as short as its text, and the picture is drawn
    across the borders and over its neighbours. Measured on a real worksheet:
    every question image landed outside the cell it belonged to.

    Inline content contributes to the cell's height, so the table makes room
    for it. That is the whole repair.

    Only pictures already inside a cell are moved. One anchored elsewhere may
    genuinely belong where it was put -- a logo in a letterhead, a watermark --
    and guessing its owner from coordinates is a separate problem. A picture
    sent behind the text is deliberate backdrop and is left alone.
    """
    if item.run is None:
        return False
    if _enclosing(parent_of, item.run, "tc") is None:
        return False
    # `item.behind` means a text box is stacked on this picture. An author's
    # own watermark says so on the anchor instead, and inlining one would push
    # the text it sits under down the page.
    if item.anchor.get("behindDoc") not in (None, *OFF_VALUES):
        return False
    return _anchor_to_inline(item.anchor, item.drawing, ids)


def _anchor_to_inline(anchor: Element, drawing: Element, ids: Ids) -> bool:
    """Rewrites one floating picture as inline content, in place."""
    graphic = anchor.find(q("a", "graphic"))
    extent = anchor.find(q("wp", "extent"))
    if graphic is None or extent is None:
        return False

    item_anchor, item_drawing = anchor, drawing
    inline = Element(q("wp", "inline"))
    inline.attrib.update({"distT": "0", "distB": "0", "distL": "0", "distR": "0"})
    # CT_Inline fixes this order: extent, effectExtent?, docPr, frame?, graphic.
    inline.append(extent)
    effect = item_anchor.find(q("wp", "effectExtent"))
    if effect is not None:
        inline.append(effect)
    described = item_anchor.find(q("wp", "docPr"))
    if described is None:
        described = Element(q("wp", "docPr"))
        described.attrib.update({"id": str(ids.next()), "name": "Picture"})
    inline.append(described)
    frame = item_anchor.find(q("wp", "cNvGraphicFramePr"))
    if frame is not None:
        inline.append(frame)
    inline.append(graphic)

    at = list(item_drawing).index(item_anchor)
    item_drawing.remove(item_anchor)
    item_drawing.insert(at, inline)
    return True


def _replace_textbox(parent_of: dict, item: Anchored, ids: Ids) -> bool:
    paragraph = item.paragraph
    _detach(item.drawing, item.anchor)
    if paragraph is None:
        return False
    container = parent_of.get(paragraph)
    if container is None:
        return False
    table = build_table(item, ids)
    if table is None:
        # An empty box, or one with no content to move. Nothing was converted,
        # and the report must not claim otherwise.
        return False
    index = list(container).index(paragraph)
    # A paragraph carrying <w:sectPr> *ends* its section. Inserting after it
    # would push the table into the next section, where a different page size,
    # orientation and set of margins apply -- so portrait content can end up
    # laid out landscape. Content belonging to this section must precede it.
    at = index if _ends_section(paragraph) else index + 1
    container.insert(at, table)
    # Kept in step with what just moved: the box's paragraphs are now in the
    # table's cell. A box nested in this one is anchored in one of them, and
    # the map taken before would send it to the box it has left (#119).
    parent_of[table] = container
    parent_of.update(parents(table))
    _keep_tables_apart(container, at, rtl=is_rtl(paragraph))
    _end_with_paragraph(container, rtl=is_rtl(paragraph))
    return True


def _last_block(container: Element) -> Element | None:
    """The container's last block. A body's trailing w:sectPr is not one."""
    blocks = [child for child in container if local(child.tag) != "sectPr"]
    return blocks[-1] if blocks else None


def _end_with_paragraph(container: Element, rtl: bool = False) -> None:
    """Keeps a cell, header, footer or body ending in a paragraph, as Word
    always writes them, when a table has just become its last block.

    Placed before the body's w:sectPr, never after it: section properties
    must be the body's last child.
    """
    last = _last_block(container)
    if last is None or local(last.tag) != "tbl":
        return
    if local(container.tag) not in MUST_END_WITH_A_PARAGRAPH:
        return
    container.insert(list(container).index(last) + 1, new_paragraph(rtl))


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
    # Anchored to a property boundary: unanchored, "width" also matches inside
    # mso-width-percent, and the wrong number is read as the picture's size.
    match = re.search(r"(?:^|;)\s*" + name + r"\s*:\s*([^;]+)", style, re.IGNORECASE)
    if not match:
        return None
    size = VML_LENGTH.match(match.group(1).strip())
    if not size:
        return None
    try:
        return round(float(size.group(1)) * VML_UNITS_TO_EMU[size.group(2).lower()])
    except (ValueError, KeyError):
        return None


VML_TEXT_TAGS = ("textbox", "textpath")


def _legacy_content(pict: Element) -> tuple[Element, Element] | str:
    """The one shape and image worth rewriting, or why this <w:pict> is kept.

    The old rule took any `v:shape` and any `v:imagedata` anywhere beneath the
    element and threw the rest away. A captioned photo -- a `v:group` holding a
    picture and a text box, which is what a document that began life as a .doc
    is full of -- came out as the picture alone, with the caption deleted and
    counted as a successful conversion.
    """
    if pict.find(".//" + q("v", "group")) is not None:
        return "grouped legacy shape"
    if any(pict.find(".//" + q("v", tag)) is not None for tag in VML_TEXT_TAGS):
        return "text in a legacy shape"
    shapes = pict.findall(".//" + q("v", "shape"))
    if len(shapes) != 1:
        return "several legacy shapes"
    images = shapes[0].findall(".//" + q("v", "imagedata"))
    if len(images) != 1:
        return "legacy shape without a single image"
    if _is_floating_vml(shapes[0]):
        return "legacy watermark or background"
    return shapes[0], images[0]


def _is_floating_vml(shape: Element) -> bool:
    """Whether a VML shape is placed over the page rather than in the text.

    Word writes a picture watermark as an absolutely positioned header shape
    with a negative z-index. Rebuilt as *inline* content it stops being a
    backdrop: it takes up its full height in the header and pushes the page
    down.
    """
    style = (shape.get("style") or "").lower()
    if re.search(r"(?:^|;)\s*position\s*:\s*absolute", style):
        return True
    depth = re.search(r"(?:^|;)\s*z-index\s*:\s*(-?\d+)", style)
    return bool(depth and int(depth.group(1)) < 0)


def fix_legacy_pictures(root: Element, ids: Ids) -> dict:
    """Rewrites VML-only pictures as modern inline DrawingML.

    Word keeps some images as <w:pict> with a VML shape and no DrawingML
    sibling -- usually pasted or very old content. Google's importer ignores
    them entirely, so the picture simply disappears. Rebuilding them as an
    inline <w:drawing> referencing the same relationship keeps the image.

    Only a <w:pict> that holds nothing but that one picture is rewritten.
    Anything else -- a group, a caption, a watermark -- is left exactly as it
    was and named in the report, because replacing it means destroying the part
    we cannot carry across.

    Only touches a <w:pict> whose parent is a run: it also appears inside
    <w:object>, where a <w:drawing> is not a legal child.
    """
    report: dict = {"legacyPictures": 0, "legacyKept": {}}
    for container, pict in _pairs(root, q("w", "pict")):
        if local(container.tag) != "r":
            continue
        content = _legacy_content(pict)
        if isinstance(content, str):
            report["legacyKept"][content] = report["legacyKept"].get(content, 0) + 1
            continue
        shape, image = content
        rid = image.get(q("r", "id"))
        if not rid:
            report["legacyKept"]["legacy shape without a stored image"] = (
                report["legacyKept"].get("legacy shape without a stored image", 0) + 1
            )
            continue
        style = shape.get("style") or ""
        cx = vml_length(style, "width")
        cy = vml_length(style, "height")
        if not cx or not cy:
            report["legacyKept"]["legacy shape without a stated size"] = (
                report["legacyKept"].get("legacy shape without a stated size", 0) + 1
            )
            continue
        at = list(container).index(pict)
        container.remove(pict)
        container.insert(at, make_inline_drawing(rid, cx, cy, shape.get("alt") or "Picture", ids))
        report["legacyPictures"] += 1
    return report


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


def empty_paragraphs(root: Element) -> set[Element]:
    """Paragraphs with nothing in them but properties, as the part stands now.

    The set holds the elements themselves, so it stays right only while the
    passes *move* paragraphs rather than rebuild them. A converted text box's
    paragraphs are the same objects in their new cell, so an author's blank
    line there is still recognised. A pass that copied a paragraph (deepcopy,
    or building a new one from its children) would make the copy look like
    something this converter emptied, and it would be removed.
    """
    return {p for p in root.iter(q("w", "p")) if _is_empty(p)}


def remove_empty_paragraphs(root: Element, already_empty: set[Element]) -> None:
    """Removes paragraphs this converter emptied, and only those.

    A paragraph whose only content was an ink annotation, or a fallback branch
    with no choice, has nothing left once that content is gone; leaving it
    would add a blank line the author never typed.

    A paragraph that was *already* empty is the author's own blank line --
    answer space on a worksheet, spacing in a letter, or a page break carried
    by `w:pageBreakBefore`. Those are layout, not residue, so `already_empty`
    (taken before any pass ran) is never touched. Removing them was issue #42:
    pages merged and worksheets lost their writing space.

    Deliberately conservative about emptiness too. Listing "text bearing" tags
    instead loses fields, footnote and comment references, symbols, embedded
    objects and bookmarks -- all real content that simply is not <w:t>.
    """
    for container, paragraph in _pairs(root, q("w", "p")):
        if paragraph in already_empty or not _is_empty(paragraph):
            continue
        properties = paragraph.find(q("w", "pPr"))
        # The final paragraph of a section carries sectPr: page size, margins
        # and orientation all live there.
        if properties is not None and properties.find(q("w", "sectPr")) is not None:
            continue
        # A cell, header, footer or text box must keep at least one paragraph;
        # <w:hdr/> or a <w:tc> with none is invalid.
        if len(container.findall(q("w", "p"))) <= 1:
            continue
        siblings = list(container)
        # These must *end* with a paragraph, not merely hold one. A text box
        # whose last block is a table leaves a cell ending in w:tbl, and the
        # paragraph appended to fix that is itself blank -- so without this it
        # is removed again on the way out.
        if (
            _last_block(container) is paragraph
            and local(container.tag) in MUST_END_WITH_A_PARAGRAPH
        ):
            continue
        # A paragraph wedged between two tables is what stops them merging.
        at = siblings.index(paragraph)
        if 0 < at < len(siblings) - 1:
            if local(siblings[at - 1].tag) == "tbl" and local(siblings[at + 1].tag) == "tbl":
                continue
        container.remove(paragraph)


MUST_END_WITH_A_PARAGRAPH = {"tc", "hdr", "ftr", "txbxContent", "body", "footnote", "endnote"}


def _is_empty(paragraph: Element) -> bool:
    return all(_hollow(child) for child in paragraph)


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


def is_empty_box(content: Element) -> bool:
    """Whether a text box holds nothing worth moving into a table.

    Word leaves these behind: a real worksheet was found carrying four boxes
    of 0.24 by 0.25 inches with no content at all, artefacts of editing rather
    than anything an author put there.

    Converting one produces a floating table with an empty cell, plus the
    empty paragraphs that keep tables apart -- clutter that occupies space on
    the page and can displace what is around it. There is nothing to make
    editable, which is the only reason the conversion exists.

    Emptiness is judged the same conservative way as remove_empty_paragraphs:
    anything that is not a property element counts as content, so a box
    holding only a picture, a field or a footnote reference is kept.
    """
    paragraphs = content.findall(q("w", "p"))
    if not paragraphs:
        return True
    return all(_hollow(child) for paragraph in paragraphs for child in paragraph)


def build_table(item: Anchored, ids: Ids) -> Element | None:
    content = item.anchor.find(".//" + q("w", "txbxContent"))
    if content is None or is_empty_box(content):
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
    if len(cell) == 0 or local(cell[-1].tag) != "p":
        # OOXML requires a cell to *end* with a paragraph, not merely to hold
        # one: a text box whose last block is a table left the cell ending in
        # w:tbl. This paragraph is ours, so it has no author's direction to
        # inherit.
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


# A twip (dxa) is a twentieth of a point; an EMU is 914400 to the inch.
EMU_PER_DXA = 635
# Word's own default left and right cell padding when <w:tblCellMar> is absent.
DEFAULT_CELL_MARGIN_DXA = 108


def _measure(element: Element | None, name: str) -> int | None:
    """A stated width in twips.

    Read as a decimal, not an integer. Word writes `w:w="11504.0"` and the
    schema allows it, but `int()` refuses it -- so a real worksheet's `w:tblW`
    measured as nothing, the table's own width was left behind when its columns
    were narrowed, and the two then disagreed by three quarters of an inch.
    A length with a unit ("210mm") is read too; see docx.twips.
    """
    if element is None:
        return None
    value = twips(element.get(q("w", name)))
    return None if value is None else round(value)


class Sections:
    """Which section's page lays out an element, as the part stands now.

    Built per pass, because passes move content: a table a text box became
    is a new block, and belongs to whichever section it was inserted into.
    A header or footer has no body, so it is measured by `fallback`, the
    main document's last section.
    """

    def __init__(self, root: Element, parent_of: dict, fallback: Element | None = None) -> None:
        body = root.find(q("w", "body"))
        self.owner = governing_sections(body) if body is not None else {}
        self.parent_of = parent_of
        self.fallback = fallback

    def of(self, element: Element | None) -> Element | None:
        if not self.owner:
            return self.fallback
        return section_of(element, self.parent_of, self.owner)


def _final_section(root: Element) -> Element | None:
    """The section properties that measure the page, in dxa.

    A document with several sections of differing size is measured by its
    last one. That is the common case by a wide margin, and guessing per
    table would need the layout we are trying to avoid depending on.

    The final section's properties are the body's own ``w:sectPr``. Searching
    the whole body instead would also find the *previous* properties that a
    tracked change keeps inside ``w:sectPrChange`` -- which come last in
    document order, so a tracked page-setup change would be measured by the
    page it used to have.
    """
    body = root.find(q("w", "body"))
    if body is None:
        return None
    section = body.find(q("w", "sectPr"))
    if section is not None:
        return section
    # No body-level properties: fall back to the last section break, still
    # only from paragraphs directly in the body.
    breaks = body.findall(q("w", "p") + "/" + q("w", "pPr") + "/" + q("w", "sectPr"))
    return breaks[-1] if breaks else None


def printable_width(section: Element | None) -> int | None:
    """The usable width in dxa of one section's page."""
    if section is None:
        return None
    width = _measure(section.find(q("w", "pgSz")), "w")
    margins = section.find(q("w", "pgMar"))
    left = _measure(margins, "left") or 0
    right = _measure(margins, "right") or 0
    if width is None or width <= 0:
        return None
    usable = width - left - right
    return usable if usable > 0 else None


def printable_height(section: Element | None) -> int | None:
    """The usable height in dxa of one section's page.

    Mirrors printable_width: top and bottom margins instead of left and right.
    """
    if section is None:
        return None
    height = _measure(section.find(q("w", "pgSz")), "h")
    margins = section.find(q("w", "pgMar"))
    top = _measure(margins, "top") or 0
    bottom = _measure(margins, "bottom") or 0
    if height is None or height <= 0:
        return None
    usable = height - top - bottom
    return usable if usable > 0 else None


def _cell_padding(table: Element) -> int:
    margins = table.find(q("w", "tblPr") + "/" + q("w", "tblCellMar"))
    left = _measure(margins.find(q("w", "left")) if margins is not None else None, "w")
    right = _measure(margins.find(q("w", "right")) if margins is not None else None, "w")
    left = DEFAULT_CELL_MARGIN_DXA if left is None else left
    right = DEFAULT_CELL_MARGIN_DXA if right is None else right
    return left + right


def _scale_extent(holder: Element, factor: float) -> bool:
    """Shrinks one drawing's stated size: its frame, and its own shape's size.

    Only the outermost shape's a:ext. A group's children are drawn at their
    own size times the group's (a:ext over a:chExt), so scaling the group
    already scales them; scaling them as well shrank them twice while their
    offsets shrank once, and scrambled the group (#118).
    """
    changed = False
    extent = holder.find(q("wp", "extent"))
    sizes = [extent] if extent is not None else []
    data = holder.find(q("a", "graphic") + "/" + q("a", "graphicData"))
    for shape in data if data is not None else []:
        for properties in shape:
            if local(properties.tag) in ("spPr", "grpSpPr"):
                size = properties.find(q("a", "xfrm") + "/" + q("a", "ext"))
                if size is not None:
                    sizes.append(size)
    for size in sizes:
        for axis in ("cx", "cy"):
            try:
                value = int(size.get(axis, ""))
            except ValueError:
                continue
            size.set(axis, str(max(1, round(value * factor))))
            changed = True
    return changed


def fit_tables_to_page(root: Element, fallback: Element | None = None) -> dict:
    """Narrows a table wider than the page, and the pictures inside it.

    Word lets a table state columns totalling more than the paper can hold; it
    simply runs off the edge. Measured on a real worksheet: about 575pt of
    columns in about 523pt of printable width, so every row crossed the right
    margin whatever the images did.

    Scaling the grid alone is not enough -- a picture sized for the old column
    would then overflow the new one -- so anything too wide for the cell it
    now sits in is brought down by the same reasoning.

    Only top-level tables are measured. A nested table is bounded by its cell,
    not the page, and shrinking it against the page would compound.

    Each table is measured by its own section's page: a landscape table ahead
    of a portrait section fits the landscape page, not the portrait one.
    """
    report = {"tablesNarrowed": 0, "picturesShrunk": 0}
    parent_of = parents(root)
    sections = Sections(root, parent_of, fallback)
    for table in root.iter(q("w", "tbl")):
        if _enclosing(parent_of, parent_of.get(table), "tbl") is not None:
            continue
        usable = printable_width(sections.of(table))
        if usable is None:
            continue
        grid = table.find(q("w", "tblGrid"))
        columns = grid.findall(q("w", "gridCol")) if grid is not None else []
        measured = [_measure(column, "w") for column in columns]
        widths = [width for width in measured if width is not None]
        if not widths or len(widths) != len(measured):
            continue
        total = sum(widths)
        if total <= usable:
            continue
        factor = usable / total
        for column, width in zip(columns, widths, strict=True):
            column.set(q("w", "w"), str(max(1, round(width * factor))))
        # The table's own preferred width, if stated in twips, must agree with
        # its narrowed grid; left alone it would still claim the old width.
        _scale_dxa(table.find(q("w", "tblPr") + "/" + q("w", "tblW")), factor)
        # Only this table's cells: a nested table keeps its grid, so its cells
        # must keep their widths too or the two would disagree.
        for cell in table.iter(q("w", "tc")):
            if _enclosing(parent_of, parent_of.get(cell), "tbl") is table:
                _scale_dxa(cell.find(q("w", "tcPr") + "/" + q("w", "tcW")), factor)
        report["tablesNarrowed"] += 1
        report["picturesShrunk"] += _shrink_pictures(table, parent_of, factor)
    return report


def _scale_dxa(width: Element | None, factor: float) -> None:
    """Scales a stated width, but only one given in twips."""
    measured = _measure(width, "w")
    if width is not None and measured and width.get(q("w", "type")) == "dxa":
        width.set(q("w", "w"), str(max(1, round(measured * factor))))


def _shrink_pictures(table: Element, parent_of: dict, factor: float) -> int:
    """Brings inline pictures down with the columns that now hold them."""
    padding = _cell_padding(table)
    shrunk = 0
    for cell in table.iter(q("w", "tc")):
        if _enclosing(parent_of, parent_of.get(cell), "tbl") is not table:
            continue
        available = _cell_width(cell, parent_of) - padding
        if available <= 0:
            continue
        limit = available * EMU_PER_DXA
        for inline in cell.iter(q("wp", "inline")):
            width = _measure_emu(inline)
            if width is None or width <= limit:
                continue
            if _scale_extent(inline, limit / width):
                shrunk += 1
    return shrunk


def _measure_emu(inline: Element) -> int | None:
    extent = inline.find(q("wp", "extent"))
    try:
        return int(extent.get("cx", "")) if extent is not None else None
    except ValueError:
        return None


def _measure_emu_height(inline: Element) -> int | None:
    extent = inline.find(q("wp", "extent"))
    try:
        return int(extent.get("cy", "")) if extent is not None else None
    except ValueError:
        return None


def _span(element: Element | None, name: str) -> int:
    """A w:gridSpan or w:gridBefore count, defaulting to what Word assumes."""
    found = element.find(q("w", name)) if element is not None else None
    try:
        value = int(found.get(q("w", "val"), "")) if found is not None else None
    except ValueError:
        value = None
    if value is None:
        return 1 if name == "gridSpan" else 0
    return max(0, value)


def _cell_width(cell: Element, parent_of: dict) -> int:
    """The cell's own stated width, already scaled, or the grid columns it spans.

    Returns 0 when the cell cannot be placed on the grid, so its pictures are
    left alone rather than shrunk against a guess.
    """
    stated = cell.find(q("w", "tcPr") + "/" + q("w", "tcW"))
    measured = _measure(stated, "w")
    if measured and stated is not None and stated.get(q("w", "type")) == "dxa":
        return measured
    table = _enclosing(parent_of, cell, "tbl")
    grid = table.find(q("w", "tblGrid")) if table is not None else None
    columns = grid.findall(q("w", "gridCol")) if grid is not None else []
    widths = [_measure(column, "w") or 0 for column in columns]
    row = _enclosing(parent_of, cell, "tr")
    if row is None:
        return 0
    # Walk the row to find where this cell starts on the grid: cells skipped
    # by w:gridBefore, then every earlier cell's w:gridSpan.
    start = _span(row.find(q("w", "trPr")), "gridBefore")
    for sibling in row.findall(q("w", "tc")):
        span = _span(sibling.find(q("w", "tcPr")), "gridSpan")
        if sibling is cell:
            if start + span > len(widths):
                return 0
            return sum(widths[start : start + span])
        start += span
    return 0


# Issue #55. Measured on a real worksheet: 45 question pictures were anchored to
# the paragraph *above* the table they belonged to and positioned by offset so
# they appeared over its cells. Google places them against the page instead, so
# they land across borders and over one another.
#
# The column is recoverable exactly, because a grid states its column widths.
# The row is not: `w:trHeight` is a minimum, not a height, and where a table
# falls in the flow depends on everything above it. So the row is taken from the
# order the pictures themselves are stacked in, and only when that order matches
# the free rows one for one. Anything else is reported, never guessed.
BAND_EMU = 274320  # 0.3in; two pictures closer than this are on the same row
LABEL_CHARS = 4  # "1." or "12." numbers a question; longer text is content
# Across: only frames that start where the text column starts, because the
# offset is compared against the grid directly. Down: any frame, because the
# vertical offsets are only ever ranked against each other -- but every picture
# above one table must share a frame, or the ranking compares two origins.
# (The left margin strip starts at the paper's edge, not the text column; it
# arrives here already restated as a page offset, see _offset.)
# The inside margin is read as it always was, as the text column's start: which
# side it is on depends on the page, and the report says so (see
# replace_anchors).
ACROSS_FRAMES = {"column", "margin", "insideMargin", "text"}
# A page-relative offset counts from the paper's edge, so the margin has to come
# off it before it means anything against a grid. That is exact arithmetic, not
# a guess, so those pictures are worth recovering rather than reporting.
PAGE_FRAMES = {"page"}


def _margin(section: Element | None, side: str) -> int | None:
    """One page margin in EMU, from the section's current properties.

    Never from w:sectPrChange, which keeps the margins a tracked page-setup
    change replaced.
    """
    if section is None:
        return None
    margin = _measure(section.find(q("w", "pgMar")), side)
    return None if margin is None else margin * EMU_PER_DXA


def _starts_the_page(root: Element, paragraph: Element) -> bool:
    """Whether this paragraph's top is the top of the text area, exactly.

    Only then is the constant between a page-relative and a paragraph-relative
    vertical offset a known quantity -- the top margin -- rather than something
    to be guessed at. It has to be the body's first block, with nothing above it
    and no space asked for before it.
    """
    body = root.find(q("w", "body"))
    if body is None or len(body) == 0 or body[0] is not paragraph:
        return False
    spacing = paragraph.find(q("w", "pPr") + "/" + q("w", "spacing"))
    return spacing is None or spacing.get(q("w", "before")) in (None, "0")


def _offset(anchor: Element, axis: str, geometry: dict | None = None) -> tuple[str, int] | None:
    """A picture's frame and offset on one axis, or nothing if it is unstated.

    An offset into a margin strip is restated from the paper's edge, as a
    "page" offset (see docx.margin_area), using `geometry`, the page_geometry
    of the picture's section. An inside or outside strip changes side with the
    page, which is not known here; one is read as before and reported (see
    replace_anchors).
    """
    position = anchor.find(q("wp", "position" + axis))
    if position is None:
        return None
    frame = position.get("relativeFrom")
    offset = position.find(q("wp", "posOffset"))
    if frame is None or offset is None:
        return None
    try:
        value = int(offset.text or "")
    except ValueError:
        return None
    if frame in MARGIN_AREAS[axis]:
        area = margin_area(axis, frame, geometry)
        return None if area is None else ("page", area[0] + value)
    return frame, value


def _bands(offsets: list[int]) -> list[list[int]]:
    """Vertical offsets grouped into rows, nearest first."""
    grouped: list[list[int]] = []
    for offset in sorted(offsets):
        if grouped and offset - grouped[-1][-1] <= BAND_EMU:
            grouped[-1].append(offset)
        else:
            grouped.append([offset])
    return grouped


def _candidate_rows(table: Element, column: int, parent_of: dict, holding: int) -> list[Element]:
    """Cells in one column holding a question number and exactly `holding` pictures."""
    found = []
    for row in table.findall(q("w", "tr")):
        cell = _cell_at(row, column, column)
        if cell is None:
            return []
        # The lower part of a vertically merged cell shows its first part's
        # content, not its own, so nothing is put there.
        if _continues_merge(cell):
            continue
        # Something is still floating inside this cell; whatever it is, this row
        # is not settled and nothing should be dropped into it.
        if list(cell.iter(q("wp", "anchor"))):
            continue
        if len(list(cell.iter(q("wp", "inline")))) != holding:
            continue
        text = "".join(node.text or "" for node in cell.iter(q("w", "t"))).strip()
        if len(text) <= LABEL_CHARS:
            found.append(cell)
    return found


def _row_cells(row: Element) -> list[tuple[int, int, Element]]:
    """This row's cells, each with the first grid column it covers and how many.

    A cell's place on the grid is not its place in the row: w:gridBefore skips
    columns at the start, and a w:gridSpan cell covers several. Indexing the
    row's cells by grid column put a picture in the cell after the one it was
    drawn over.
    """
    found = []
    start = _span(row.find(q("w", "trPr")), "gridBefore")
    for cell in row.findall(q("w", "tc")):
        span = max(1, _span(cell.find(q("w", "tcPr")), "gridSpan"))
        found.append((start, span, cell))
        start += span
    return found


def _cell_at(row: Element, first: int, last: int) -> Element | None:
    """The one cell covering grid columns first to last, or None if none does."""
    for start, span, cell in _row_cells(row):
        if start <= first and last < start + span:
            return cell
    return None


def _continues_merge(cell: Element) -> bool:
    merge = cell.find(q("w", "tcPr") + "/" + q("w", "vMerge"))
    return merge is not None and merge.get(q("w", "val")) in (None, "continue")


def _target_rows(table: Element, column: int, parent_of: dict) -> list[Element]:
    """The cells in one column waiting for a picture.

    Usually the empty ones. But a worksheet often gives each question two
    pictures -- one in the cell and one floating over it -- and once #34 has
    inlined the first, every cell already holds exactly one. Measured on a real
    worksheet: 10 pictures above a table whose ten cells were already full, all
    of them a different image at a different size from the one below. Appending
    a second to each is then the only reading that places anything at all.
    """
    empty = _candidate_rows(table, column, parent_of, 0)
    return empty or _candidate_rows(table, column, parent_of, 1)


def _page_anchored(anchor: Element, geometry: dict | None) -> bool:
    down = _offset(anchor, "V", geometry)
    return down is not None and down[0] == "page"


def _picture_only_paragraph(paragraph: Element) -> bool:
    """True for a paragraph that carries nothing but anchored pictures, or
    nothing at all -- a blank spacer between two stacked question images.

    A worksheet often puts each picture in its own paragraph rather than
    several in one, so the run of paragraphs directly above a table has to be
    walked, not just the last one. But the walk has to stop at the first
    paragraph holding anything else -- a question's own instructions, say --
    or a picture belonging to that text would be swept up with it.
    """
    text = "".join(node.text or "" for node in paragraph.iter(q("w", "t"))).strip()
    if text:
        return False
    return all(classify(a)[0] == "picture" for a in paragraph.iter(q("wp", "anchor")))


def place_orphan_pictures(
    root: Element,
    ids: Ids,
    fallback: Element | None = None,
    uncertain: set[Element] | None = None,
) -> dict:
    """Moves a picture floating above a table into the cell it was drawn over.

    A picture this pass reports as uncertain is added to `uncertain`, so the
    geometry pass after it can leave it alone rather than count it again.
    """
    parent_of = parents(root)
    sections = Sections(root, parent_of, fallback)
    report = {"picturesPlaced": 0, "picturesUnplaced": 0, "picturesGeometryUncertain": 0}
    uncertain = set() if uncertain is None else uncertain
    for container in list(root.iter()):
        blocks = list(container)
        for index, block in enumerate(blocks[:-1]):
            if local(block.tag) != "p" or local(blocks[index + 1].tag) != "tbl":
                continue
            run = []
            i = index
            while i >= 0 and local(blocks[i].tag) == "p" and _picture_only_paragraph(blocks[i]):
                run.append(blocks[i])
                i -= 1
            run.reverse()
            anchors = sum(len(list(p.iter(q("wp", "anchor")))) for p in run)
            if not anchors:
                continue
            # A page break inside the run puts its first pictures on another
            # page from the table, whatever their offsets say.
            if _page_relation(blocks, i + 1, index + 1) == "different":
                report["picturesUnplaced"] += anchors
                continue
            _place_above(root, run, blocks[index + 1], parent_of, sections, ids, report, uncertain)
    return report


def _table_start(table: Element, geometry: dict, width: int) -> int | None:
    """Where a table's first column starts, in EMU from the text column's
    start -- the frame `_place_above` measures pictures in (#168).

    Read from what the table states: a floating position (`w:tblpPr`), an
    alignment (`w:jc`), or an indent (`w:tblInd`). `width` is the table's grid
    width in EMU. None where the answer isn't exact: an aligned rather than
    offset floating table, an indent that isn't in twips, a centred or
    right-aligned table on a page whose size isn't stated, or columns running
    right to left. The indent is taken as ECMA-376 states it, to the table's
    leading edge. Word's older layouts put that edge a cell margin further
    left; like the rest of this pass, this doesn't model that.
    """
    properties = table.find(q("w", "tblPr"))
    if properties is None:
        return 0
    rtl = properties.find(q("w", "bidiVisual"))
    if rtl is not None and rtl.get(q("w", "val")) not in OFF_VALUES:
        return None

    indent = properties.find(q("w", "tblInd"))
    if indent is None or indent.get(q("w", "type")) == "nil":
        inset: int | None = 0
    elif indent.get(q("w", "type")) in (None, "dxa"):
        stated = _measure(indent, "w")
        inset = None if stated is None else stated * EMU_PER_DXA
    else:
        inset = None

    position = properties.find(q("w", "tblpPr"))
    if position is not None:
        across = _measure(position, "tblpX")
        if position.get(q("w", "tblpXSpec")) is not None or across is None or inset != 0:
            return None
        anchor = position.get(q("w", "horzAnchor"))
        if anchor in ("margin", "text"):
            return across * EMU_PER_DXA
        if anchor == "page" and geometry.get("left") is not None:
            return across * EMU_PER_DXA - geometry["left"]
        return None

    alignment = properties.find(q("w", "jc"))
    align = None if alignment is None else alignment.get(q("w", "val"))
    if align in (None, "left", "start"):
        return inset
    if align not in ("center", "right", "end"):
        return None
    page, left, right = geometry.get("width"), geometry.get("left"), geometry.get("right")
    if page is None or left is None or right is None:
        return None
    # An aligned table ignores its indent.
    spare = page - left - right - width
    return spare // 2 if align == "center" else spare


def _place_above(
    root: Element,
    paragraphs: list[Element],
    table: Element,
    parent_of: dict,
    sections: Sections,
    ids: Ids,
    report: dict,
    uncertain: set[Element],
) -> None:
    anchors = [anchor for paragraph in paragraphs for anchor in paragraph.iter(q("wp", "anchor"))]
    if not anchors:
        return
    pictures = [
        anchor
        for anchor in anchors
        if classify(anchor)[0] == "picture" and anchor.get("behindDoc") in (None, *OFF_VALUES)
    ]
    grid = table.find(q("w", "tblGrid"))
    # `if grid` would ask whether the element has children, which is not the
    # question and is false for a grid written as a single self-closing tag.
    stated = (
        [_measure(col, "w") for col in grid.findall(q("w", "gridCol"))] if grid is not None else []
    )
    columns = [width for width in stated if width is not None]
    # Anything we cannot measure, and any paragraph carrying something other
    # than plain pictures, is left exactly as it is.
    if len(pictures) != len(anchors) or not columns or len(columns) != len(stated):
        report["picturesUnplaced"] += len(anchors)
        return

    section = sections.of(table)
    geometry = page_geometry(section)
    margin = _margin(section, "left")
    start_of_table = _table_start(table, geometry, sum(columns) * EMU_PER_DXA)
    if start_of_table is None:
        # Where the columns are isn't known, so neither is which one a
        # picture was drawn over.
        report["picturesGeometryUncertain"] += len(pictures)
        uncertain.update(pictures)
        return

    edges, running = [], start_of_table
    for width in columns:
        edges.append((running, running + width * EMU_PER_DXA))
        running += width * EMU_PER_DXA

    placed: dict[int, list[tuple[int, Element]]] = {}
    frames: set[str] = set()
    straddling: list[Element] = []
    for anchor in pictures:
        across, down = _offset(anchor, "H", geometry), _offset(anchor, "V", geometry)
        # _measure_emu takes the element that *holds* wp:extent, not the extent.
        drawn = _measure_emu(anchor)
        if across is None or down is None or drawn is None:
            report["picturesUnplaced"] += len(anchors)
            return
        if across[0] in PAGE_FRAMES:
            if margin is None:
                report["picturesUnplaced"] += len(anchors)
                return
            start = across[1] - margin
        elif across[0] in ACROSS_FRAMES:
            start = across[1]
        else:
            report["picturesUnplaced"] += len(anchors)
            return
        frames.add(down[0])
        # The whole picture, not its centre (#55): one crossing a column
        # boundary belongs to neither column for certain, and moving it into
        # one would then shrink it to that column's width.
        end = start + drawn
        column = next(
            (n for n, (left, right) in enumerate(edges) if left <= start and end <= right), None
        )
        if column is None:
            if any(start < right and end > left for left, right in edges):
                straddling.append(anchor)
                continue
            report["picturesUnplaced"] += len(anchors)
            return
        placed.setdefault(column, []).append((down[1], anchor))

    if straddling:
        # Which row each picture belongs to is read from the whole stack, so
        # the ones that do fit are left too, as the geometry pass would.
        report["picturesGeometryUncertain"] += len(straddling)
        report["picturesUnplaced"] += len(anchors) - len(straddling)
        uncertain.update(straddling)
        return

    if len(frames) > 1:
        # Two origins ranked against each other would order the pictures
        # arbitrarily -- unless the constant between them is known exactly,
        # which it is when the paragraph starts the text area.
        top = _margin(section, "top")
        if (
            frames != {"page", "paragraph"}
            or top is None
            or not _starts_the_page(root, paragraphs[0])
        ):
            report["picturesUnplaced"] += len(anchors)
            return
        for column, found in placed.items():
            placed[column] = [
                (down - top if _page_anchored(anchor, geometry) else down, anchor)
                for down, anchor in found
            ]

    targets: list[tuple[Element, Element]] = []
    for column, found in placed.items():
        rows = _target_rows(table, column, parent_of)
        # Sorted by offset only: two pictures at the same height must not be
        # compared as elements, which has no meaning and no stable answer.
        ordered = sorted(found, key=lambda pair: pair[0])
        bands = _bands([down for down, _ in ordered])
        # One band per free row, or the stack says nothing about which row is
        # which, and the honest answer is to leave every picture where it is.
        if len(bands) != len(rows):
            report["picturesUnplaced"] += len(anchors)
            return
        taken = iter(ordered)
        for band, cell in zip(bands, rows, strict=True):
            targets.extend((cell, next(taken)[1]) for _ in band)

    for cell, anchor in targets:
        _move_into_cell(cell, anchor, parent_of, ids, report)


def _move_into_cell(
    cell: Element, anchor: Element, parent_of: dict, ids: Ids, report: dict
) -> None:
    drawing = parent_of.get(anchor)
    run = parent_of.get(drawing) if drawing is not None else None
    source = parent_of.get(run) if run is not None else None
    if drawing is None or run is None or source is None:
        report["picturesUnplaced"] += 1
        return
    if not _anchor_to_inline(anchor, drawing, ids):
        report["picturesUnplaced"] += 1
        return
    source.remove(run)
    holder = Element(q("w", "p"))
    properties = SubElement(holder, q("w", "pPr"))
    # Centred rather than placed at a recovered offset: the offset described a
    # position on the page, and inside a cell it would mean something else.
    SubElement(properties, q("w", "jc")).set(q("w", "val"), "center")
    holder.append(run)
    cell.append(holder)
    report["picturesPlaced"] += 1


# The rest of #55: a picture anchored *anywhere* in the document, not just
# the paragraph immediately above its table -- assigned by rectangle
# geometry rather than document order. That needs a page-absolute rectangle
# for both the picture and every candidate cell, which is only ever exact
# when the table itself states its own page position (w:tblpPr) and every
# row an exact height. Most real worksheets have neither: a table is
# usually left to normal flow, and w:trHeight is a minimum, not a height
# (see place_orphan_pictures above). So this pass is deliberately narrow --
# it only ever touches a table it can measure exactly, and only a picture
# that overlaps one -- and leaves everything else for the order-based pass.
TABLE_ABSOLUTE_H = {"page", "margin"}
TABLE_ABSOLUTE_V = {"page", "margin"}
# A picture's own relativeFrom carries more values than a table's tblpPr
# does (ST_RelFromH/V vs the much smaller CT_TblPPr enum). Only the ones
# whose edge is unambiguous without knowing mirroring or RTL are safe here.
# Margin strips arrive already restated against the page (see _offset).
PICTURE_ABSOLUTE_H = {"page", "margin", "insideMargin"}
PICTURE_ABSOLUTE_V = {"page", "margin"}


def _page_offset(frame: str, value: int, margin: int | None, safe: set[str]) -> int | None:
    """A frame-relative offset translated to one absolute origin: the page's
    own top-left corner. `value` and `margin` must already be in the same
    unit -- this does no conversion of its own. None if the frame isn't one
    this can convert without guessing (`text`/`paragraph`, or a margin we
    don't have)."""
    if frame == "page":
        return value
    if frame in safe and margin is not None:
        return value + margin
    return None


def _table_geometry(
    table: Element, left_margin: int | None, top_margin: int | None
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]] | None:
    """This table's column and row edges, in EMU, absolute from the page's
    top-left corner. None unless both are exact: a stated `w:tblpPr`
    position on the page or margin, a full numeric grid, and every row an
    exact `w:trHeight`.
    """
    properties = table.find(q("w", "tblPr"))
    position = properties.find(q("w", "tblpPr")) if properties is not None else None
    if position is None:
        return None
    x = _measure(position, "tblpX")
    y = _measure(position, "tblpY")
    if x is None or y is None:
        return None
    # left_margin/top_margin are already EMU (see _margin), so tblpX/Y are
    # converted to EMU here too, before anything is added to them.
    horz = position.get(q("w", "horzAnchor")) or ""
    vert = position.get(q("w", "vertAnchor")) or ""
    origin_x = _page_offset(horz, x * EMU_PER_DXA, left_margin, TABLE_ABSOLUTE_H)
    origin_y = _page_offset(vert, y * EMU_PER_DXA, top_margin, TABLE_ABSOLUTE_V)
    if origin_x is None or origin_y is None:
        return None

    grid = table.find(q("w", "tblGrid"))
    stated = [_measure(c, "w") for c in grid.findall(q("w", "gridCol"))] if grid is not None else []
    columns = [w for w in stated if w is not None]
    if not columns or len(columns) != len(stated):
        return None
    col_edges, running = [], origin_x
    for width in columns:
        col_edges.append((running, running + width * EMU_PER_DXA))
        running += width * EMU_PER_DXA

    row_edges, running = [], origin_y
    for row in table.findall(q("w", "tr")):
        height = row.find(q("w", "trPr") + "/" + q("w", "trHeight"))
        if height is None or height.get(q("w", "hRule")) != "exact":
            return None
        stated_height = _measure(height, "val")
        if stated_height is None:
            return None
        row_edges.append((running, running + stated_height * EMU_PER_DXA))
        running += stated_height * EMU_PER_DXA

    return col_edges, row_edges


# Without Word's record of where its pages broke (w:lastRenderedPageBreak),
# nothing says where a page ends, so only a picture anchored within this many
# blocks of a table counts as on the same page -- the same few lines, not the
# same document.
MAX_BLOCKS_APART = 3


def _starts_a_page(section: Element) -> bool:
    kind = section.find(q("w", "type"))
    return kind is None or kind.get(q("w", "val")) != "continuous"


def _page_marks(block: Element) -> set[str]:
    """What in this block says a page ends.

    "before": the block's own paragraph starts a new page; "ends": it ends a
    section that starts the next one on a new page; "inside": a page ends
    somewhere within it. Only current properties are read: the old ones a
    tracked change keeps (w:pPrChange, w:sectPrChange) sit a level deeper.
    """
    marks = set()
    for paragraph in block.iter(q("w", "p")):
        properties = paragraph.find(q("w", "pPr"))
        if properties is None:
            continue
        own = paragraph is block
        before = properties.find(q("w", "pageBreakBefore"))
        if before is not None and before.get(q("w", "val")) not in OFF_VALUES:
            marks.add("before" if own else "inside")
        section = properties.find(q("w", "sectPr"))
        if section is not None and _starts_a_page(section):
            marks.add("ends" if own else "inside")
    if any(br.get(q("w", "type")) == "page" for br in block.iter(q("w", "br"))):
        marks.add("inside")
    if block.find(".//" + q("w", "lastRenderedPageBreak")) is not None:
        marks.add("inside")
    return marks


def _page_relation(blocks: list[Element], first: int, last: int, limit: int | None = None) -> str:
    """Whether blocks[first] and blocks[last] are on one page: "same",
    "different" or "unknown".

    Different when a page ends between them; unknown when one ends inside
    either of them (the picture's side of it is not known), or, given a
    `limit`, when more blocks than that lie between them.
    """
    first, last = min(first, last), max(first, last)
    # A content control's own marks are its blocks', which are listed after it.
    for block in blocks[first + 1 : last]:
        if local(block.tag) != "sdt" and _page_marks(block):
            return "different"
    head, tail = _page_marks(blocks[first]), _page_marks(blocks[last])
    if first == last:
        # A block's own start and end do not divide it.
        return "unknown" if (head | tail) - {"before", "ends"} else "same"
    if "ends" in head or "before" in tail:
        return "different"
    if head - {"before"} or tail - {"ends"}:
        return "unknown"
    if limit is not None and last - first - 1 > limit:
        return "unknown"
    return "same"


def place_pictures_by_table_geometry(
    root: Element,
    ids: Ids,
    fallback: Element | None = None,
    reported: set[Element] | frozenset[Element] = frozenset(),
) -> dict:
    """Assigns a still-floating picture to the cell its rectangle sits
    inside, wherever in the document it was anchored -- unlike
    place_orphan_pictures, this doesn't depend on document order at all.

    Deliberately conservative: only a table whose page position and every
    row height are stated exactly is measured (see _table_geometry), and
    only a picture whose rectangle overlaps one of those tables is this
    pass's business at all. A picture nowhere near a measurable table --
    a letterhead logo, say -- is never even considered, let alone reported.

    Page coordinates repeat on every page, so an overlap means nothing
    unless the two are on the same page (#134): a picture on page 5 at the
    spot a table fills on page 2 is not in that table. Where that cannot be
    shown, the picture stays where it is and is reported as uncertain.

    A picture in `reported` was already left and reported by the pass
    before this one, so it is skipped: it can only be uncertain here too.
    """
    parent_of = parents(root)
    sections = Sections(root, parent_of, fallback)
    report = {"picturesPlaced": 0, "picturesUnplaced": 0, "picturesGeometryUncertain": 0}

    body = root.find(q("w", "body"))
    blocks = list(body_blocks(body if body is not None else root))
    order = {block: n for n, block in enumerate(blocks)}
    # Word records where its pages broke when it saves. With that record, no
    # break between two blocks means one page, however far apart they are.
    rendered = root.find(".//" + q("w", "lastRenderedPageBreak")) is not None
    limit = None if rendered else MAX_BLOCKS_APART

    def block_index(element: Element | None) -> int | None:
        while element is not None and element not in order:
            element = parent_of.get(element)
        return None if element is None else order[element]

    tables = []
    for table in root.iter(q("w", "tbl")):
        if _enclosing(parent_of, parent_of.get(table), "tbl") is not None:
            continue  # a nested table is bounded by its cell, not the page
        section = sections.of(table)
        measured = _table_geometry(table, _margin(section, "left"), _margin(section, "top"))
        if measured is not None:
            tables.append((table, *measured, block_index(table)))
    if not tables:
        return report

    for anchor in list(root.iter(q("wp", "anchor"))):
        if classify(anchor)[0] != "picture" or anchor.get("behindDoc") not in (None, *OFF_VALUES):
            continue
        if anchor in reported:
            continue
        section = sections.of(anchor)
        geometry = page_geometry(section)
        across, down = _offset(anchor, "H", geometry), _offset(anchor, "V", geometry)
        width, height = _measure_emu(anchor), _measure_emu_height(anchor)
        if across is None or down is None or width is None or height is None:
            continue
        # A picture's own offset (wp:posOffset) is already EMU, same as
        # _margin -- no conversion needed here.
        x0 = _page_offset(across[0], across[1], _margin(section, "left"), PICTURE_ABSOLUTE_H)
        y0 = _page_offset(down[0], down[1], _margin(section, "top"), PICTURE_ABSOLUTE_V)
        if x0 is None or y0 is None:
            continue
        x1, y1 = x0 + width, y0 + height
        at = block_index(anchor)

        overlapping = [
            (table, col_edges, row_edges, table_at)
            for table, col_edges, row_edges, table_at in tables
            if not (
                x1 <= col_edges[0][0]
                or x0 >= col_edges[-1][1]
                or y1 <= row_edges[0][0]
                or y0 >= row_edges[-1][1]
            )
        ]
        if not overlapping:
            continue  # no overlap with any table -- not this pass's business
        relations = [
            "unknown"
            if at is None or table_at is None
            else _page_relation(blocks, at, table_at, limit)
            for *_, table_at in overlapping
        ]
        if "same" not in relations:
            if "unknown" in relations:
                report["picturesGeometryUncertain"] += 1
            continue  # every table it overlaps is on another page
        table, col_edges, row_edges, _ = overlapping[relations.index("same")]

        cell = _cell_under(table, col_edges, row_edges, (x0, y0, x1, y1))
        if cell is None:
            report["picturesGeometryUncertain"] += 1
            continue
        _move_into_cell(cell, anchor, parent_of, ids, report)
    return report


def _cell_under(
    table: Element,
    col_edges: list[tuple[int, int]],
    row_edges: list[tuple[int, int]],
    box: tuple[int, int, int, int],
) -> Element | None:
    """The one cell a rectangle lies wholly inside, or None if it is not one.

    Found through the grid (#117): a merged cell covers several columns, and
    w:gridBefore leaves columns with no cell at all. The lower part of a
    vertically merged cell shows the content of its first part, not its own,
    so nothing is placed by it.
    """
    x0, y0, x1, y1 = box
    row = next((n for n, (top, bottom) in enumerate(row_edges) if top <= y0 and y1 <= bottom), None)
    first = next((n for n, (left, right) in enumerate(col_edges) if left <= x0 < right), None)
    last = next((n for n, (left, right) in enumerate(col_edges) if left < x1 <= right), None)
    if row is None or first is None or last is None:
        return None
    cell = _cell_at(table.findall(q("w", "tr"))[row], first, last)
    if cell is None or _continues_merge(cell):
        return None
    return cell


def _cell_pictures(cell: Element) -> bool:
    """Whether this cell's own paragraphs hold an inline picture."""
    return any(list(p.iter(q("wp", "inline"))) for p in cell.findall(q("w", "p")))


# CT_TrPrBase's declared child order (ECMA-376 Part 1, SS17.4.83). w:cantSplit
# has to land between w:wAfter and w:trHeight, or Word rejects the row.
TR_PR_ORDER = [
    "cnfStyle",
    "divId",
    "gridBefore",
    "gridAfter",
    "wBefore",
    "wAfter",
    "cantSplit",
    "trHeight",
    "tblHeader",
    "tblCellSpacing",
    "jc",
    "hidden",
]


def _insert_in_schema_order(parent: Element, tag: str, order: list[str]) -> Element:
    """Adds a child of `parent` at the position its schema requires."""
    position = order.index(tag)
    index = len(parent)
    for i, child in enumerate(parent):
        name = local(child.tag)
        if name in order and order.index(name) > position:
            index = i
            break
    element = Element(q("w", tag))
    parent.insert(index, element)
    return element


def protect_picture_rows(
    root: Element, had_pictures: set[Element], fallback: Element | None = None
) -> dict:
    """Adds w:cantSplit to a table row that has just gained an inline picture.

    A picture #34 moved into a cell makes the row grow to hold it, and an
    unprotected row can still split across a page break -- the picture ends
    up above the break and its question text below it, or the reverse. See
    #55.

    Skipped when the row's own picture is already taller than the printable
    page: Word cannot honour w:cantSplit there, the row overflows onto the
    next page regardless, and forcing the attempt only makes that overflow
    less predictable.
    """
    parent_of = parents(root)
    sections = Sections(root, parent_of, fallback)
    rows: list[Element] = []
    seen: set[Element] = set()
    for cell in root.iter(q("w", "tc")):
        if cell in had_pictures or not _cell_pictures(cell):
            continue
        row = _enclosing(parent_of, cell, "tr")
        if row is None or row in seen:
            continue
        seen.add(row)
        rows.append(row)

    protected = 0
    for row in rows:
        usable = printable_height(sections.of(row))
        if usable is not None:
            heights = [
                _measure_emu_height(inline)
                for cell in row.iter(q("w", "tc"))
                for inline in cell.iter(q("wp", "inline"))
            ]
            tallest = max((h for h in heights if h is not None), default=0)
            if tallest and tallest / EMU_PER_DXA > usable:
                continue
        properties = row.find(q("w", "trPr"))
        if properties is None:
            # CT_Row: w:tblPrEx?, w:trPr?, then cell content -- w:trPr comes
            # right after w:tblPrEx if the row has one, otherwise first.
            properties = Element(q("w", "trPr"))
            index = 1 if len(row) and local(row[0].tag) == "tblPrEx" else 0
            row.insert(index, properties)
        if properties.find(q("w", "cantSplit")) is None:
            _insert_in_schema_order(properties, "cantSplit", TR_PR_ORDER)
        protected += 1
    return {"rowsProtected": protected}


def _release_reserved_space(
    root: Element, before: set[Element], holders: set[Element], blank: set[Element]
) -> int:
    """Stops protecting blank lines that were holding a picture's place.

    #42 is right that an author's blank line is layout and must survive. But a
    worksheet reserves room for a picture floating *over* a cell by typing
    blank lines inside it, and since #34 that picture is inline content of the
    cell and brings its own height. Keeping both counts the same space twice:
    measured on a real worksheet, 32 cells carried 9.7in of blank lines on top
    of 63.8in of picture -- an extra page of nothing.

    So only in a cell that has just gained a picture, and only for lines that
    were already blank, the protection is lifted. Everything else about
    `remove_empty_paragraphs` still applies, including never emptying a cell.

    A cell a text box became is new, but the pictures it holds were already
    inline in the box, beside the author's own spacing (#116). `holders` is
    every paragraph that held an inline picture before any pass ran, so only
    a picture that arrived since counts as gained.
    """
    released = 0
    for cell in root.iter(q("w", "tc")):
        if cell in before or not _gained_picture(cell, holders):
            continue
        for paragraph in cell.findall(q("w", "p")):
            if paragraph in blank:
                blank.discard(paragraph)
                released += 1
    return released


def _gained_picture(cell: Element, holders: set[Element]) -> bool:
    return any(
        paragraph not in holders and list(paragraph.iter(q("wp", "inline")))
        for paragraph in cell.findall(q("w", "p"))
    )


def transform(root: Element, ids: Ids | None = None, fallback: Element | None = None) -> dict:
    """Applies every pass, in the order they depend on each other.

    `fallback` measures a part with no body of its own (a header or footer):
    the main document's last section.
    """
    ids = ids or Ids()
    # Before anything moves: which blank lines are the author's own.
    already_empty = empty_paragraphs(root)
    # Which cells already held a picture, so we can tell which ones gain one.
    had_pictures = {cell for cell in root.iter(q("w", "tc")) if _cell_pictures(cell)}
    holders = {p for p in root.iter(q("w", "p")) if list(p.iter(q("wp", "inline")))}
    strip_fallbacks_keep_choice(root)
    # Ink runs go first, so replace_anchors never sees them -- which is why the
    # count is carried across rather than taken from that pass.
    ink = remove_ink_runs(root)
    remove_background(root)
    report = replace_anchors(root, ids, fallback)
    report["ink"] += ink
    # After the anchors: a legacy picture inside a text box only becomes
    # reachable once that text box has been moved into its table.
    legacy = fix_legacy_pictures(root, ids)
    report["legacyPictures"] = legacy["legacyPictures"]
    # Kept, not converted: named beside the other things we could not carry
    # across, so a person knows to look at them.
    for label, count in legacy["legacyKept"].items():
        report["unsupported"][label] = report["unsupported"].get(label, 0) + count
    # Last: the tables must hold every picture that is going to end up in them
    # before they can be measured against the page.
    # Before the tables are measured: a picture that lands in a cell changes
    # how wide that table needs to be.
    uncertain: set[Element] = set()
    report.update(place_orphan_pictures(root, ids, fallback, uncertain))
    # A different reach than the pass above: by rectangle geometry rather
    # than document order, so it also catches a picture anchored nowhere
    # near its table in the XML -- but only for a table exact enough to
    # measure at all. Picture counts are summed, not replaced.
    geometry = place_pictures_by_table_geometry(root, ids, fallback, uncertain)
    report["picturesPlaced"] += geometry["picturesPlaced"]
    report["picturesUnplaced"] += geometry["picturesUnplaced"]
    report["picturesGeometryUncertain"] += geometry["picturesGeometryUncertain"]
    report.update(fit_tables_to_page(root, fallback))
    # After fitting: a picture #34 or #55 moved into a row may have just been
    # shrunk to the column, which changes whether the row still fits a page.
    report.update(protect_picture_rows(root, had_pictures, fallback))
    report["blankLinesReclaimed"] = _release_reserved_space(
        root, had_pictures, holders, already_empty
    )
    remove_empty_paragraphs(root, already_empty)
    return report


IGNORABLE = q("mc", "Ignorable")


def _declared_namespaces(root: Element) -> set[str]:
    """Every namespace URI something in this tree actually uses."""
    used: set[str] = set()
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.startswith("{"):
            used.add(element.tag[1:].partition("}")[0])
        for name in element.attrib:
            if name.startswith("{"):
                used.add(name[1:].partition("}")[0])
    return used


def prune_ignorable(root: Element) -> None:
    """Drops mc:Ignorable prefixes that the output will not declare.

    ElementTree declares only the namespaces something in the tree uses, so a
    root that arrived carrying `mc:Ignorable="w14 w15 wp14 w16se w16cid"` came
    out still naming prefixes whose xmlns declaration had gone. Markup
    Compatibility (ECMA-376 Part 3) requires an Ignorable prefix to be
    declared, so the file was invalid even when nothing in it had changed --
    and it is handed to people to open in Word.
    """
    stated = root.get(IGNORABLE)
    if stated is None:
        return
    known = {**EXTENSION_NS, **NS}
    used = _declared_namespaces(root)
    kept = [prefix for prefix in stated.split() if known.get(prefix) in used]
    if kept:
        root.set(IGNORABLE, " ".join(kept))
    else:
        # An empty mc:Ignorable is legal, but saying nothing is clearer than
        # saying "ignore nothing".
        del root.attrib[IGNORABLE]


def serialise(root: Element) -> bytes:
    prune_ignorable(root)
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


# Only the strongest recommendations are applied without asking. PPTX applies
# any non-manual-review candidate; DOCX deliberately does not, because the
# medium-confidence entries include handwriting families, and a phonics
# worksheet set in a different hand is the wrong teaching material rather than
# a formatting difference. See docs/font-substitution.md.
APPLIED_CONFIDENCE = "high"

FONT_SLOTS = ("ascii", "hAnsi", "cs", "eastAsia")


def substitutions_to_apply(package: Package) -> dict[str, str]:
    """Families safe to replace without a person looking first.

    Four things disqualify a recommendation, and each for its own reason:

    * not `SUBSTITUTED` -- there is nothing to apply
    * `manualReview` -- the service has said a person should decide
    * anything below high confidence -- see APPLIED_CONFIDENCE
    * symbol or embedded families -- a symbol font's glyphs are code-point
      mapped, so substituting one turns a tick into a letter; an embedded
      font's glyphs travel with the document and need no replacing at all
    """
    chosen: dict[str, str] = {}
    for requirement in font_requirements(package):
        if requirement.get("symbol") or requirement.get("embedded"):
            continue
        result = requirement.get("compatibility") or {}
        replacement = result.get("replacement")
        if (
            result.get("status") != "SUBSTITUTED"
            or result.get("manualReview")
            or result.get("confidence") != APPLIED_CONFIDENCE
            or not isinstance(replacement, str)
        ):
            continue
        chosen[requirement["family"]] = replacement
    return chosen


def apply_substitutions(root: Element, mapping: dict[str, str]) -> Counter:
    """Rewrites literal `w:rFonts` names, counting each family it replaced.

    Runs, styles and numbering all name fonts the same way, so one pass over a
    part covers every literal mention in it. Theme references carry no family
    name and are handled by rewriting the theme itself.

    Counting per family rather than in total is what lets the report name what
    changed. "Nine fonts were replaced" is not something a person can check;
    "Century Gothic became Montserrat" is.
    """
    applied: Counter = Counter()
    if not mapping:
        return applied
    for element in root.iter(q("w", "rFonts")):
        for slot in FONT_SLOTS:
            name = element.get(q("w", slot))
            if name in mapping:
                element.set(q("w", slot), mapping[name])
                applied[(name, mapping[name])] += 1
    return applied


def apply_theme_substitutions(root: Element, mapping: dict[str, str]) -> Counter:
    """Rewrites the families a theme declares.

    A run using `w:asciiTheme` names no font, so there is nothing in the body
    to rewrite -- the family lives in the theme, and that is the only place
    changing it has any effect. Without this a document formatted the way Word
    formats one by default would report substitutions and receive none.
    """
    applied: Counter = Counter()
    if not mapping:
        return applied
    for element in root.iter():
        typeface = element.get("typeface")
        if typeface in mapping:
            element.set("typeface", mapping[typeface])
            applied[(typeface, mapping[typeface])] += 1
    return applied


EXTENDED_PROPERTIES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"
)
EXTENDED_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"


def saved_page_count(package: Package) -> int | None:
    """The page count Word saved in docProps/app.xml, or None.

    Word's own count from its last layout, so evidence for the read-back to
    compare against (#53), not a rule: another program may not write it, and
    may write it wrong.
    """
    for relationship in package.relationships(""):
        if relationship["type"] != EXTENDED_PROPERTIES or not relationship["resolved"]:
            continue
        pages = package.xml(relationship["resolved"]).find("{" + EXTENDED_NS + "}Pages")
        text = (pages.text or "").strip() if pages is not None else ""
        return int(text) if text.isdigit() and int(text) > 0 else None
    return None


def render(package: Package, destination: Path) -> dict:
    """Writes a Google-ready .docx beside the original and reports what changed."""
    ids = Ids()
    report: dict[str, Any] = {
        "textboxes": 0,
        "pictures": 0,
        # What the layout passes actually did. These exist to be measured on a
        # real document: without them "pictures: 128" reads as work done when
        # the pictures may simply have been counted and left where they were.
        "picturesInlined": 0,
        "blankLinesReclaimed": 0,
        "picturesPlaced": 0,
        "picturesUnplaced": 0,
        "tablesNarrowed": 0,
        "picturesShrunk": 0,
        "picturesGeometryUncertain": 0,
        "positionsPageSideUncertain": 0,
        "ink": 0,
        "legacyPictures": 0,
        "equations": 0,
        "regeneratedFields": 0,
        "fontSubstitutions": {},
        "unsupported": {},
        "parts": [],
    }
    rewritten: dict[str, bytes] = {}
    tokens: Counter = Counter()

    # Decided once, from the resolved requirements, then applied wherever a
    # family is named. Deciding per part would ask the same question repeatedly
    # and could answer it differently in each.
    mapping = substitutions_to_apply(package)
    applied: Counter = Counter()
    # A header or footer has no section of its own; which sections use it is
    # not worked out, so it is measured by the body's last one.
    last_section = _final_section(package.xml(DOCX.main_part))

    for name in story_parts(package):
        root = package.xml(name)
        if name == DOCX.main_part:
            # Body text only. Drive's plain-text export does not reliably
            # include headers, so counting them would invent mismatches.
            tokens = Counter(source_text(root).split())
        part_report = transform(root, ids, None if name == DOCX.main_part else last_section)
        if name == DOCX.main_part:
            # What is uploaded, after the transform: a text box that became a
            # table is a table Google should have too (#53).
            body = root.find(q("w", "body"))
            report["topLevelTables"] = sum(
                1
                for block in body_blocks(body if body is not None else [])
                if local(block.tag) == "tbl"
            )
        # Every part, unlike the token comparison above: that is body-only
        # because comparing header text would invent mismatches, which says
        # nothing about where an equation can be. An equation in a letterhead
        # is as unverified as one in the body.
        #
        # Counted after the transform, so a construct restated inside
        # mc:Fallback is counted once rather than twice.
        report["equations"] += count_equations(root)
        report["regeneratedFields"] += count_regenerated_fields(root)
        applied.update(apply_substitutions(root, mapping))
        rewritten[name] = serialise(root)
        report["parts"].append(name)
        for key in (
            "textboxes",
            "pictures",
            "picturesInlined",
            "blankLinesReclaimed",
            "picturesPlaced",
            "picturesUnplaced",
            "tablesNarrowed",
            "picturesShrunk",
            "picturesGeometryUncertain",
            "positionsPageSideUncertain",
            "ink",
            "legacyPictures",
        ):
            report[key] += part_report[key]
        for label, count in part_report["unsupported"].items():
            report["unsupported"][label] = report["unsupported"].get(label, 0) + count

    # styles.xml and theme1.xml are not story parts, but between them they hold
    # most of the font names in a real document: a well-built template keeps
    # its fonts in styles, and Word's default is a theme reference. Rewriting
    # only the body would substitute almost nothing.
    if STYLES_PART in package.names:
        styles = package.xml(STYLES_PART)
        found = apply_substitutions(styles, mapping)
        if found:
            applied.update(found)
            rewritten[STYLES_PART] = serialise(styles)
    if THEME_PART in package.names:
        theme = package.xml(THEME_PART)
        found = apply_theme_substitutions(theme, mapping)
        if found:
            applied.update(found)
            rewritten[THEME_PART] = serialise(theme)

    report["fontSubstitutions"] = {
        f"{original} -> {replacement}": count
        for (original, replacement), count in sorted(applied.items())
    }
    report["tokens"] = dict(tokens)
    report["sourcePages"] = saved_page_count(package)

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


FALLBACK = q("mc", "Fallback")
WORD_BREAKS = {q("w", "tab"), q("w", "ptab"), q("w", "br"), q("w", "cr")}
# Characters Word keeps as elements rather than text (#122). A no-break
# hyphen is a hyphen on the page; a soft hyphen shows only where a line
# breaks. A symbol names a code in its font, which is not a character here --
# chr() of it gives the wrong letter for most symbol fonts -- so the word
# holding it is marked as not comparable instead of guessed at.
IN_WORD = {
    q("w", "noBreakHyphen"): "-",
    q("w", "softHyphen"): "",
    q("w", "sym"): UNCOMPARABLE,
}


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

    Words are rebuilt the way a reader sees them, because the export they are
    compared with is read the same way (issue #43):

    * Runs within a paragraph are joined with nothing between them. Word splits
      one word across runs all the time -- a revision, a spell-check, bold on
      one letter -- and joining with a space turned "Photosynthesis" into two
      tokens the export never contains.
    * Paragraphs, tabs and breaks separate words, as they do on the page.
    * `mc:Fallback` is skipped. Word writes every text box twice, and counting
      the legacy copy doubled every word in it.
    * Hidden runs (`w:vanish`) are skipped: the export does not contain them.
      Hiding applied through a character style is not resolved.
    * No-break and soft hyphens are characters in the word, not gaps in it;
      a word holding a symbol is not compared at all (IN_WORD).
    """
    skip = _cached_result_text(root)
    pieces: list[str] = []
    # A depth-first walk on an explicit stack. Children are pushed in reverse
    # so they pop in reading order. A paragraph pushes None *before* its
    # children; the stack is last-in-first-out, so that None pops only after
    # every child is done, and marks where the paragraph ends.
    stack: list[Element | None] = [root]
    while stack:
        node = stack.pop()
        if node is None:  # the end of a paragraph
            pieces.append(" ")
            continue
        if not isinstance(node.tag, str) or node.tag == FALLBACK:
            continue
        if node.tag == q("w", "t"):
            # A computed field's cached value still marks a word boundary.
            pieces.append(" " if id(node) in skip else node.text or "")
            continue
        if node.tag in WORD_BREAKS:
            pieces.append(" ")
            continue
        if node.tag in IN_WORD:
            pieces.append(IN_WORD[node.tag])
            continue
        if node.tag == q("w", "r") and _is_hidden(node):
            continue
        if node.tag == q("w", "p"):
            pieces.append(" ")
            stack.append(None)
        stack.extend(reversed(list(node)))
    return "".join(pieces)


def _is_hidden(run: Element) -> bool:
    vanish = run.find(q("w", "rPr") + "/" + q("w", "vanish"))
    return vanish is not None and vanish.get(q("w", "val")) not in OFF_VALUES


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
    # Both sides through the same text_tokens (#122). The source's words are
    # already split; reading each again only normalises it, or drops it.
    source: Counter = Counter()
    for word, count in tokens.items():
        for token in text_tokens(word):
            source[token] += count
    missing = source - text_tokens(exported)
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
    original_name: str = "",
) -> dict:
    """Uploads the rendered .docx for native import, then checks what came back."""
    # imported here to avoid a cycle
    from .google import DOCS_MIME, DRIVE, SEPARATOR, clean_name, save_assets

    document = clean_name(original_name)
    output_name = f"{document}{SEPARATOR}converted" if document else "Converted document"
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
        folder = await google.folder(output_name)
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
        await save_assets(result, manifest, google, folder, report, original_name)

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
            if k
            in {
                "textboxes",
                "pictures",
                "picturesInlined",
                "blankLinesReclaimed",
                "picturesPlaced",
                "picturesUnplaced",
                "tablesNarrowed",
                "picturesShrunk",
                "picturesGeometryUncertain",
                "positionsPageSideUncertain",
                "ink",
                # A family we swapped is a change to the document, and PROJECT.md
                # says every change is reported. The Slides path has always shown
                # this; the Docs path replaced a typeface and said nothing.
                "fontSubstitutions",
                "legacyPictures",
                "equations",
                "regeneratedFields",
            }
        }
        report["conversion"]["unsupportedKept"] = render_report.get("unsupported", {})
        # Where to look, for whoever reads the saved report: never on screen,
        # and never a claim that the layout is right (#53).
        report["readBack"] = await read_back(
            google,
            uploaded["id"],
            {
                "pages": render_report.get("sourcePages"),
                "tables": render_report.get("topLevelTables"),
            },
        )
        report["verification"] = "text_checked"
        report["status"] = "completed_with_warnings"
    except ToolkitError as exc:
        report["status"] = "failed_with_partial_outputs" if report.get("folderUrl") else "failed"
        report["warnings"].append(
            warning(exc.code, exc.message, classification=C.UNSUPPORTED, detail=exc.detail)
            if exc.detail
            else warning(exc.code, exc.message, classification=C.UNSUPPORTED)
        )
        report["verification"] = "incomplete"

    # Saved to Drive by the caller, once, with everything added after this
    # returns (see google.save_report and web.py, #121).
    return report
