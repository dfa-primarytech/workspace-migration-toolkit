"""Tests for the intermediate model's schema and its validator."""

from __future__ import annotations

import copy
import json
import os
import unittest

from harness import validation


def minimal_document() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "generator": {"name": "publisher-parser", "version": "0.1.0"},
        "source": {
            "type": "publisher",
            "filename": "example.pub",
            "sha256": "0" * 64,
            "byteLength": 1024,
            "containerType": "ole2",
            "formatFamily": "microsoft-publisher",
            "supportedByParser": True,
        },
        "document": {"title": None, "pageCount": 1, "masterPageCount": 0, "metadata": {}},
        "units": {"length": "pt"},
        "fonts": [],
        "assets": {"count": 0, "placementCount": 0, "manifest": "assets.json",
                   "directory": "assets", "ids": []},
        "callbacks": {"total": 4, "counts": {"startPage": 1}},
        "pages": [{
            "id": "page_0001", "index": 0, "kind": "page",
            "width": 420.945, "height": 595.276, "unit": "pt",
            "sourceSize": {"width": None, "height": None},
            "eventRange": {"start": 1, "end": 3},
            "implicit": False, "sourceProperties": {},
            "elements": [], "warnings": [],
        }],
        "warnings": [], "limitations": [],
        "truncation": {"truncated": False, "reason": None},
    }


def text_element(identifier: str = "el_000001", z: int = 0) -> dict:
    return {
        "id": identifier, "type": "text", "pageIndex": 0,
        "bounds": {"x": 10.0, "y": 20.0, "width": 100.0, "height": 40.0, "unit": "pt"},
        "rotationDegrees": None, "zIndex": z, "parentId": None, "visible": True,
        "source": {"callback": "startTextObject", "eventIndex": 2, "endEventIndex": 8,
                   "styleEventIndex": -1, "properties": {}, "styleProperties": {}},
        "compatibility": {"status": "NATIVE", "basis": "parser-candidate",
                          "evidence": "a text frame maps to an editable Slides text box"},
        "paragraphs": [], "warnings": [],
    }


class SchemaFileTest(unittest.TestCase):
    def test_schema_file_is_valid_json_and_versioned(self):
        schema = validation.load_schema()
        self.assertEqual(schema["version"], "1.0.0")
        self.assertIn("documentBundle", schema["$defs"])
        self.assertIn("assetsBundle", schema["$defs"])
        self.assertIn("reportBundle", schema["$defs"])

    def test_schema_fixes_the_shared_compatibility_vocabulary(self):
        schema = validation.load_schema()
        statuses = schema["$defs"]["compatibility"]["properties"]["status"]["enum"]
        self.assertEqual(statuses,
                         ["NATIVE", "SUBSTITUTED", "FLATTENED", "UNSUPPORTED", "IGNORED"])

    def test_schema_declares_both_image_routes(self):
        schema = validation.load_schema()
        routes = schema["$defs"]["image"]["properties"]["route"]["enum"]
        self.assertEqual(sorted(routes), ["bitmapFillShape", "drawGraphicObject"])


class DocumentValidationTest(unittest.TestCase):
    def test_a_minimal_document_validates(self):
        self.assertEqual(validation.validate_document_kind(minimal_document(), "documentBundle"), [])

    def test_a_missing_required_field_is_reported(self):
        document = minimal_document()
        del document["units"]
        problems = validation.validate_document_kind(document, "documentBundle")
        self.assertTrue(any("units" in str(p) for p in problems))

    def test_an_unknown_element_type_is_rejected(self):
        document = minimal_document()
        element = text_element()
        element["type"] = "hologram"
        document["pages"][0]["elements"].append(element)
        problems = validation.validate_document_kind(document, "documentBundle")
        self.assertTrue(any("not one of" in p.message for p in problems))

    def test_an_unknown_property_is_rejected(self):
        document = minimal_document()
        document["surprise"] = 1
        problems = validation.validate_document_kind(document, "documentBundle")
        self.assertTrue(any("not allowed" in p.message for p in problems))

    def test_a_boolean_is_not_accepted_where_a_number_belongs(self):
        document = minimal_document()
        document["pages"][0]["width"] = True
        problems = validation.validate_document_kind(document, "documentBundle")
        self.assertTrue(problems)

    def test_a_bad_sha256_is_rejected(self):
        document = minimal_document()
        document["source"]["sha256"] = "not-a-hash"
        problems = validation.validate_document_kind(document, "documentBundle")
        self.assertTrue(any("does not match" in p.message for p in problems))

    def test_problem_messages_do_not_echo_the_offending_string(self):
        # A validation message ends up in a log. Document content must not.
        document = minimal_document()
        document["source"]["sha256"] = "secret-pupil-name"
        problems = validation.validate_document_kind(document, "documentBundle")
        self.assertTrue(problems)
        self.assertFalse(any("secret-pupil-name" in str(p) for p in problems))


class ReferenceValidationTest(unittest.TestCase):
    def test_a_consistent_document_has_no_reference_problems(self):
        document = minimal_document()
        document["pages"][0]["elements"].append(text_element())
        self.assertEqual(validation.validate_references(document, {"assets": []}), [])

    def test_an_unresolved_asset_id_is_reported(self):
        document = minimal_document()
        element = text_element()
        element["type"] = "image"
        element["image"] = {"assetId": "asset_0009", "route": "drawGraphicObject",
                            "shapeKind": None, "polygonIsRectangular": True,
                            "polygon": [], "path": []}
        document["pages"][0]["elements"].append(element)
        problems = validation.validate_references(document, {"assets": []})
        self.assertTrue(any("not in the manifest" in p.message for p in problems))

    def test_an_asset_use_pointing_at_no_element_is_reported(self):
        document = minimal_document()
        assets = {"assets": [{"id": "asset_0001", "useCount": 1,
                              "uses": [{"elementId": "el_999999"}]}]}
        document["assets"]["count"] = 1
        document["assets"]["ids"] = ["asset_0001"]
        problems = validation.validate_references(document, assets)
        self.assertTrue(any("not in the document" in p.message for p in problems))

    def test_out_of_order_z_index_is_reported(self):
        document = minimal_document()
        document["pages"][0]["elements"] = [text_element("el_000001", 1),
                                            text_element("el_000002", 0)]
        problems = validation.validate_references(document, {"assets": []})
        self.assertTrue(any("z-order" in p.message for p in problems))

    def test_duplicate_element_ids_are_reported(self):
        document = minimal_document()
        document["pages"][0]["elements"] = [text_element("el_000001", 0),
                                            text_element("el_000001", 1)]
        problems = validation.validate_references(document, {"assets": []})
        self.assertTrue(any("duplicate" in p.message for p in problems))

    def test_a_forward_parent_reference_is_reported(self):
        document = minimal_document()
        child = text_element("el_000001", 0)
        child["parentId"] = "el_000002"
        document["pages"][0]["elements"] = [child, text_element("el_000002", 1)]
        problems = validation.validate_references(document, {"assets": []})
        self.assertTrue(any("earlier element" in p.message for p in problems))

    def test_a_verified_compatibility_claim_is_rejected_in_a_parser_bundle(self):
        # The parser has checked nothing against Google. A bundle claiming
        # otherwise did not come from the parser.
        document = minimal_document()
        element = text_element()
        element["compatibility"]["basis"] = "verified"
        document["pages"][0]["elements"].append(element)
        problems = validation.validate_references(document, {"assets": []})
        self.assertTrue(any("parser-candidate" in p.message for p in problems))

    def test_page_count_must_match_the_pages_of_kind_page(self):
        document = minimal_document()
        document["document"]["pageCount"] = 4
        problems = validation.validate_references(document, {"assets": []})
        self.assertTrue(any("pageCount" in p.path for p in problems))

    def test_master_pages_do_not_count_towards_page_count(self):
        document = minimal_document()
        master = copy.deepcopy(document["pages"][0])
        master.update({"id": "master_0001", "kind": "master", "index": 0})
        document["pages"].insert(0, master)
        self.assertEqual(validation.validate_references(document, {"assets": []}), [])


if __name__ == "__main__":
    unittest.main()
