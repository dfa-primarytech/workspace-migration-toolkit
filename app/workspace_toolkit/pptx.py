from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# Type annotation only; XML parsing always uses defusedxml.
from xml.etree.ElementTree import Element  # nosec B405

from .config import Settings
from .errors import ToolkitError
from .model import Compatibility as C
from .model import emu_to_points, warning
from .package import Package, digest

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def paragraphs(root: Element) -> list[dict]:
    result = []
    for p in root.findall(".//a:p", NS):
        runs = []
        for child in p:
            if local(child.tag) in {"r", "fld"}:
                prop = child.find("a:rPr", NS)
                text = child.find("a:t", NS)
                runs.append(
                    {
                        "text": text.text or "" if text is not None else "",
                        "sourceStyle": dict(prop.attrib) if prop is not None else {},
                    }
                )
            elif local(child.tag) == "br":
                runs.append({"text": "\n", "sourceStyle": {}})
        prop = p.find("a:pPr", NS)
        result.append({"runs": runs, "sourceStyle": dict(prop.attrib) if prop is not None else {}})
    return result


def geometry(element: Element) -> dict:
    xfrm = next((e for e in element.iter() if local(e.tag) == "xfrm"), None)
    if xfrm is None:
        return {"bounds": None, "rotation": None}
    off = next((e for e in xfrm if local(e.tag) == "off"), None)
    ext = next((e for e in xfrm if local(e.tag) == "ext"), None)
    bounds = None
    if off is not None and ext is not None:
        try:
            bounds = {
                "x": emu_to_points(off.attrib["x"]),
                "y": emu_to_points(off.attrib["y"]),
                "width": emu_to_points(ext.attrib["cx"]),
                "height": emu_to_points(ext.attrib["cy"]),
            }
        except (KeyError, ValueError) as exc:
            raise ToolkitError(
                "invalid_geometry", "The presentation contains invalid object coordinates."
            ) from exc
    return {
        "bounds": bounds,
        "rotation": int(xfrm.get("rot", "0")) / 60000,
        "sourceTransform": {
            "attributes": dict(xfrm.attrib),
            "children": [{"kind": local(e.tag), **e.attrib} for e in xfrm],
        },
    }


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
    resources = []
    for name in sorted(package.names):
        if name.endswith(".rels"):
            parent, filename = name.rsplit("/", 1) if "/" in name else ("", name)
            part = (
                ""
                if name == "_rels/.rels"
                else parent.removesuffix("_rels") + filename.removesuffix(".rels")
            )
            relationships[part] = package.relationships(part)
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
        if name.endswith(".xml"):
            root = package.xml(name)
            for node in root.iter():
                if node.get("typeface"):
                    fonts.add(node.attrib["typeface"])
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
                elif pars and kind == "shape":
                    kind = "text"
                obj = {
                    "id": oid,
                    "type": kind,
                    "zIndex": len(elements),
                    "parentId": parent_id,
                    "paragraphs": pars,
                    "sourceKind": tag,
                    **geometry(node),
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
                    walk(node, oid)

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
        if asset["kind"] in {"audio", "video", "embedded"}:
            warnings.append(
                warning(
                    "embedded_asset",
                    "An embedded item was preserved separately; playback or editability needs review.",
                    assetId=asset["id"],
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
        "fonts": [{"name": font, "status": "UNKNOWN"} for font in sorted(fonts)],
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
        "fonts": manifest["fonts"],
        "warnings": warnings,
        "verification": "not_converted",
        "classificationBasis": "Preflight candidates, not verified Google compatibility.",
    }
