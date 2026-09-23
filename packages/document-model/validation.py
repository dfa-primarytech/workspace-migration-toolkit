"""Validation for the intermediate document representation.

Two layers, because they catch different bugs.

``validate_against_schema`` walks ``schema.json``: types, required keys,
enums, patterns, ``additionalProperties``. It is a focused subset of JSON
Schema -- enough for this schema, and dependency-free, which matters
because this package is imported by tests that must run without a
network or a virtualenv.

``validate_bundle`` then checks what no schema can: that an element's
``assetId`` resolves, that every asset use points back at an element that
exists, that each page's elements agree about which page they are on, and
that z-order is a real paint order rather than a set of arbitrary
integers. Those are the invariants a renderer will rely on.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.json")

COMPATIBILITY_STATUSES = ("NATIVE", "SUBSTITUTED", "FLATTENED", "UNSUPPORTED", "IGNORED")
ELEMENT_TYPES = (
    "text",
    "image",
    "table",
    "shape",
    "line",
    "path",
    "group",
    "wrapper",
    "unknown",
)
IMAGE_ROUTES = ("drawGraphicObject", "bitmapFillShape")


class Problem:
    """One validation failure, with the path that reached it."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Problem({self.path!r}, {self.message!r})"


def load_schema(path: str = SCHEMA_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "boolean":
        return isinstance(value, bool)
    if expected in ("number", "integer"):
        # bool is an int in Python; a boolean where a number belongs is a
        # real error, so exclude it explicitly.
        if isinstance(value, bool):
            return False
    python_type = _JSON_TYPES.get(expected)
    return python_type is not None and isinstance(value, python_type)


class _Validator:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.defs = schema.get("$defs", {})

    def resolve(self, node: dict[str, Any]) -> dict[str, Any]:
        seen = 0
        while "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError(f"unsupported $ref: {ref}")
            node = self.defs[ref[len("#/$defs/") :]]
            seen += 1
            if seen > 32:
                raise ValueError("$ref chain too deep")
        return node

    def check(self, value: Any, node: dict[str, Any], path: str, problems: list[Problem]) -> None:
        node = self.resolve(node)

        if "oneOf" in node:
            branches = node["oneOf"]
            matched = [b for b in branches if not self._branch_problems(value, b, path)]
            if len(matched) != 1:
                problems.append(
                    Problem(
                        path, f"matched {len(matched)} of {len(branches)} alternatives, expected 1"
                    )
                )
            else:
                self.check(value, matched[0], path, problems)
            return

        expected = node.get("type")
        if expected is not None:
            options = expected if isinstance(expected, list) else [expected]
            if not any(_matches_type(value, option) for option in options):
                problems.append(
                    Problem(path, f"expected type {'|'.join(options)}, got {type(value).__name__}")
                )
                return

        if "const" in node and value != node["const"]:
            problems.append(Problem(path, f"expected the constant {node['const']!r}"))
        if "enum" in node and value not in node["enum"]:
            problems.append(Problem(path, f"{value!r} is not one of {node['enum']!r}"))
        if "pattern" in node and isinstance(value, str):
            if re.search(node["pattern"], value) is None:
                # Never echo the value: it can carry document content.
                problems.append(Problem(path, f"does not match {node['pattern']!r}"))

        if isinstance(value, dict):
            self._check_object(value, node, path, problems)
        elif isinstance(value, list) and "items" in node:
            for index, item in enumerate(value):
                self.check(item, node["items"], f"{path}[{index}]", problems)

    def _check_object(
        self, value: dict[str, Any], node: dict[str, Any], path: str, problems: list[Problem]
    ) -> None:
        properties = node.get("properties", {})
        for key in node.get("required", []):
            if key not in value:
                problems.append(Problem(path, f"missing required property {key!r}"))
        additional = node.get("additionalProperties", True)
        for key, item in value.items():
            child = f"{path}.{key}" if path else key
            if key in properties:
                self.check(item, properties[key], child, problems)
            elif isinstance(additional, dict):
                self.check(item, additional, child, problems)
            elif additional is False:
                problems.append(Problem(child, "property is not allowed by the schema"))

    def _branch_problems(self, value: Any, node: dict[str, Any], path: str) -> list[Problem]:
        problems: list[Problem] = []
        self.check(value, node, path, problems)
        return problems


def validate_against_schema(
    instance: Any, schema: dict[str, Any] | None = None, path: str = ""
) -> list[Problem]:
    """Validates one bundle file against schema.json."""
    schema = schema if schema is not None else load_schema()
    problems: list[Problem] = []
    _Validator(schema).check(instance, schema, path, problems)
    return problems


def validate_document_kind(
    instance: Any, kind: str, schema: dict[str, Any] | None = None
) -> list[Problem]:
    """Validates against one named bundle shape rather than the oneOf.

    Naming the expected shape gives a usable error: the ``oneOf`` can only
    report that nothing matched.
    """
    schema = schema if schema is not None else load_schema()
    definition = schema["$defs"][kind]
    problems: list[Problem] = []
    _Validator(schema).check(instance, definition, "", problems)
    return problems


def _iter_elements(document: dict[str, Any]) -> Iterable[tuple]:
    for page_index, page in enumerate(document.get("pages", [])):
        for element_index, element in enumerate(page.get("elements", [])):
            yield f"pages[{page_index}].elements[{element_index}]", page, element


def validate_references(
    document: dict[str, Any], assets: dict[str, Any] | None = None
) -> list[Problem]:
    """Checks the invariants a JSON Schema cannot see."""
    problems: list[Problem] = []
    asset_ids = {asset["id"] for asset in (assets or {}).get("assets", [])}
    element_ids = set()
    seen_ids = set()

    for path, page, element in _iter_elements(document):
        identifier = element.get("id")
        if identifier in seen_ids:
            problems.append(Problem(path, f"duplicate element id {identifier!r}"))
        seen_ids.add(identifier)
        element_ids.add(identifier)

        if element.get("pageIndex") != page.get("index"):
            problems.append(
                Problem(path, "element pageIndex does not match the page it is listed under")
            )

        parent = element.get("parentId")
        if parent is not None and parent not in seen_ids:
            # Children follow their parent in paint order, so a forward
            # reference means the ordering is wrong, not just the id.
            problems.append(Problem(path, f"parentId {parent!r} is not an earlier element"))

        if element.get("type") == "image":
            image = element.get("image", {})
            asset_id = image.get("assetId")
            if asset_id is not None and assets is not None and asset_id not in asset_ids:
                problems.append(Problem(path, f"assetId {asset_id!r} is not in the manifest"))
            if image.get("route") not in IMAGE_ROUTES:
                problems.append(Problem(path, f"unknown image route {image.get('route')!r}"))

        compatibility = element.get("compatibility", {})
        if compatibility.get("status") not in COMPATIBILITY_STATUSES:
            problems.append(Problem(path, "compatibility status is not one of the shared set"))
        if compatibility.get("basis") != "parser-candidate":
            # A parser has not checked anything against Google. Anything
            # claiming otherwise did not come from this parser.
            problems.append(
                Problem(
                    path, "a parser bundle must mark every compatibility status 'parser-candidate'"
                )
            )

    for page_index, page in enumerate(document.get("pages", [])):
        z_values = [element.get("zIndex") for element in page.get("elements", [])]
        if z_values != sorted(z_values):
            problems.append(Problem(f"pages[{page_index}]", "elements are not listed in z-order"))
        if z_values and z_values != list(range(len(z_values))):
            problems.append(
                Problem(f"pages[{page_index}]", "zIndex is not a dense paint order from zero")
            )

    declared = document.get("assets", {})
    if assets is not None:
        if declared.get("count") != len(asset_ids):
            problems.append(Problem("assets.count", "does not match the manifest length"))
        if set(declared.get("ids", [])) != asset_ids:
            problems.append(Problem("assets.ids", "does not match the manifest"))
        for asset_index, asset in enumerate(assets.get("assets", [])):
            uses = asset.get("uses", [])
            if asset.get("useCount") != len(uses):
                problems.append(Problem(f"assets[{asset_index}].useCount", "does not match uses"))
            for use_index, use in enumerate(uses):
                if use.get("elementId") not in element_ids:
                    problems.append(
                        Problem(
                            f"assets[{asset_index}].uses[{use_index}]",
                            "references an element that is not in the document",
                        )
                    )

    page_count = document.get("document", {}).get("pageCount")
    real_pages = sum(1 for page in document.get("pages", []) if page.get("kind") == "page")
    if page_count != real_pages:
        problems.append(Problem("document.pageCount", "does not match the pages of kind 'page'"))

    return problems


def load_bundle(directory: str) -> dict[str, Any]:
    """Reads document.json, assets.json and report.json from a bundle."""
    bundle = {}
    for name in ("document", "assets", "report"):
        with open(os.path.join(directory, f"{name}.json"), encoding="utf-8") as handle:
            bundle[name] = json.load(handle)
    return bundle


def validate_bundle(directory: str, schema: dict[str, Any] | None = None) -> list[Problem]:
    """Validates a whole output bundle, including the asset files on disk."""
    schema = schema if schema is not None else load_schema()
    bundle = load_bundle(directory)
    problems: list[Problem] = []

    for name, kind in (
        ("document", "documentBundle"),
        ("assets", "assetsBundle"),
        ("report", "reportBundle"),
    ):
        for problem in validate_document_kind(bundle[name], kind, schema):
            problems.append(Problem(f"{name}.json:{problem.path}", problem.message))

    problems.extend(validate_references(bundle["document"], bundle["assets"]))

    versions = {name: bundle[name]["schemaVersion"] for name in bundle}
    if len(set(versions.values())) != 1:
        problems.append(Problem("schemaVersion", f"the three files disagree: {versions}"))

    for index, asset in enumerate(bundle["assets"].get("assets", [])):
        path = os.path.join(directory, asset["filename"])
        if not os.path.isfile(path):
            problems.append(Problem(f"assets[{index}].filename", "the payload is not on disk"))
            continue
        if os.path.getsize(path) != asset["byteLength"]:
            problems.append(Problem(f"assets[{index}].byteLength", "does not match the file"))

    return problems
