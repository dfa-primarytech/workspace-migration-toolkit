"""An empty PowerPoint file at a publication's page size.

Google's Slides API accepts a `pageSize` in `presentations.create` and
ignores it: the live run with PUB-001 (2026-09-29) asked for A5 and got
720 × 405 pt, Slides' default. Google's PowerPoint import does keep a deck's
own size. So a Publisher conversion starts from this: one blank slide in a
package whose only content is `p:sldSz`, imported as Slides, and then built
page by page through the API as before.

Written by hand rather than copied from a template, so that nothing in it
comes from anywhere else: a master, one blank layout, a plain theme and a
slide, which is what PowerPoint itself needs for a package to be valid.
"""

from __future__ import annotations

import io
import zipfile

EMU_PER_POINT = 12700
# PowerPoint's own limits on a slide's width and height: 1 to 56 inches.
MIN_EMU, MAX_EMU = 914_400, 51_206_400

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = "application/vnd.openxmlformats-officedocument.presentationml"
NS = f'xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"'
DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

TREE = (
    '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
    "</p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>"
)
LAYOUT_TREE = TREE.replace("<p:cSld>", '<p:cSld name="Blank">')
COLOURS = {
    "dk1": '<a:sysClr val="windowText" lastClr="000000"/>',
    "lt1": '<a:sysClr val="window" lastClr="FFFFFF"/>',
    "dk2": '<a:srgbClr val="1F1F1F"/>',
    "lt2": '<a:srgbClr val="EEEEEE"/>',
    "accent1": '<a:srgbClr val="4472C4"/>',
    "accent2": '<a:srgbClr val="ED7D31"/>',
    "accent3": '<a:srgbClr val="A5A5A5"/>',
    "accent4": '<a:srgbClr val="FFC000"/>',
    "accent5": '<a:srgbClr val="5B9BD5"/>',
    "accent6": '<a:srgbClr val="70AD47"/>',
    "hlink": '<a:srgbClr val="0563C1"/>',
    "folHlink": '<a:srgbClr val="954F72"/>',
}
FILL = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
LINE = f'<a:ln w="9525">{FILL}</a:ln>'
EFFECT = "<a:effectStyle><a:effectLst/></a:effectStyle>"


def _theme() -> str:
    colours = "".join(f"<a:{name}>{value}</a:{name}>" for name, value in COLOURS.items())
    fonts = '<a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/>'
    return (
        f'{DECL}<a:theme xmlns:a="{A}" name="Blank">'
        f'<a:themeElements><a:clrScheme name="Blank">{colours}</a:clrScheme>'
        f'<a:fontScheme name="Blank"><a:majorFont>{fonts}</a:majorFont>'
        f"<a:minorFont>{fonts}</a:minorFont></a:fontScheme>"
        f'<a:fmtScheme name="Blank"><a:fillStyleLst>{FILL * 3}</a:fillStyleLst>'
        f"<a:lnStyleLst>{LINE * 3}</a:lnStyleLst>"
        f"<a:effectStyleLst>{EFFECT * 3}</a:effectStyleLst>"
        f"<a:bgFillStyleLst>{FILL * 3}</a:bgFillStyleLst></a:fmtScheme>"
        "</a:themeElements></a:theme>"
    )


def _rels(*items: tuple[str, str, str]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{DOC}/{kind}" Target="{target}"/>'
        for rid, kind, target in items
    )
    return f'{DECL}<Relationships xmlns="{PKG}">{body}</Relationships>'


def clamp(points: float) -> int:
    return max(MIN_EMU, min(MAX_EMU, round(points * EMU_PER_POINT)))


def blank_deck(width_pt: float, height_pt: float) -> bytes:
    """A valid .pptx with one empty slide, `width_pt` × `height_pt` points."""
    width, height = clamp(width_pt), clamp(height_pt)
    clr_map = (
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
        'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
        'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
    )
    parts = {
        "[Content_Types].xml": (
            f'{DECL}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/ppt/presentation.xml" ContentType="{CT}.presentation.main+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" '
            f'ContentType="{CT}.slideMaster+xml"/>'
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" '
            f'ContentType="{CT}.slideLayout+xml"/>'
            f'<Override PartName="/ppt/slides/slide1.xml" ContentType="{CT}.slide+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": _rels(("rId1", "officeDocument", "ppt/presentation.xml")),
        "ppt/presentation.xml": (
            f"{DECL}<p:presentation {NS}>"
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
            f'<p:sldSz cx="{width}" cy="{height}"/>'
            '<p:notesSz cx="6858000" cy="9144000"/>'
            "</p:presentation>"
        ),
        "ppt/_rels/presentation.xml.rels": _rels(
            ("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
            ("rId2", "slide", "slides/slide1.xml"),
            ("rId3", "theme", "theme/theme1.xml"),
        ),
        "ppt/slideMasters/slideMaster1.xml": (
            f"{DECL}<p:sldMaster {NS}>{TREE}{clr_map}"
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
            "</p:sldMaster>"
        ),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _rels(
            ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "theme", "../theme/theme1.xml"),
        ),
        "ppt/slideLayouts/slideLayout1.xml": (
            f'{DECL}<p:sldLayout {NS} type="blank" preserve="1">'
            f"{LAYOUT_TREE}"
            "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"
        ),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _rels(
            ("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")
        ),
        "ppt/slides/slide1.xml": (
            f"{DECL}<p:sld {NS}>{TREE}<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
        ),
        "ppt/slides/_rels/slide1.xml.rels": _rels(
            ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")
        ),
        "ppt/theme/theme1.xml": _theme(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, text in parts.items():
            package.writestr(name, text.encode("utf-8"))
    return buffer.getvalue()
