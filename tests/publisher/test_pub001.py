"""Regression acceptance for PUB-001.

PUB-001 is a real school information booklet. It is never committed: the
repository holds only its SHA-256 and non-identifying structural counts,
in tests/fixtures/publisher/PUB-001/expected.json. Supply the document
itself through PUBLISHER_FIXTURE_PUB001, pointing outside the repository.

Every test here skips loudly when the fixture is absent. A skip is not a
pass, and CI must not report it as one -- see .github/workflows/
publisher.yml, which fails the acceptance job unless the fixture ran.
"""

from __future__ import annotations

import json
import os
import unittest

import harness

EXPECTED_PATH = os.path.join(harness.FIXTURE_DIR, "PUB-001", "expected.json")


def expectations() -> dict:
    with open(EXPECTED_PATH, encoding="utf-8") as handle:
        return json.load(handle)


class ExpectationsFileTest(unittest.TestCase):
    """Runs with or without the fixture: it checks the committed metadata."""

    def test_the_expectations_file_is_present_and_complete(self):
        data = expectations()
        self.assertEqual(data["id"], "PUB-001")
        self.assertEqual(len(data["sourceSha256"]), 64)
        self.assertEqual(data["supplyVia"]["environmentVariable"], harness.PUB001_ENV)
        for key in ("pageCount", "distinctAssets", "paragraphs", "fonts"):
            self.assertIn(key, data["expected"])

    def test_no_publisher_document_is_committed_to_the_fixture_directory(self):
        # The guard that matters most here. A .pub in this tree would be a
        # real school document in a public repository.
        offenders = []
        for root, _dirs, files in os.walk(harness.FIXTURE_DIR):
            for name in files:
                if name.lower().endswith((".pub", ".doc", ".docx", ".pdf")):
                    offenders.append(os.path.join(root, name))
        self.assertEqual(offenders, [])


class Pub001RegressionTest(unittest.TestCase):
    def setUp(self):
        self.parser = harness.require_parser(self)
        self.fixture = harness.require_pub001(self)
        self.expected = expectations()

    def _parse(self) -> dict:
        with harness.TempOutput() as out:
            run = harness.run_parser(self.parser, self.fixture, out)
            self.assertIn(run.returncode, (0, 3), msg=f"parser failed: {run.stderr}")
            bundle = harness.validation.load_bundle(out)
            bundle["_problems"] = harness.validation.validate_bundle(out)
            # Assets are read before the scratch directory is removed.
            bundle["_assetFiles"] = sorted(os.listdir(os.path.join(out, "assets"))) \
                if os.path.isdir(os.path.join(out, "assets")) else []
            return bundle

    def test_the_supplied_fixture_is_the_document_the_expectations_describe(self):
        # A different .pub would produce a confusing failure in every other
        # test, so check identity first.
        self.assertEqual(harness.sha256_file(self.fixture), self.expected["sourceSha256"])

    def test_the_bundle_validates_against_the_schema(self):
        bundle = self._parse()
        self.assertEqual([str(p) for p in bundle["_problems"]], [])

    def test_page_count_and_geometry(self):
        bundle = self._parse()
        document = bundle["document"]
        expected = self.expected["expected"]
        self.assertEqual(document["document"]["pageCount"], expected["pageCount"])
        tolerance = expected["pageSizeTolerancePoints"]
        for page in document["pages"]:
            if page["kind"] != "page":
                continue
            self.assertAlmostEqual(page["width"], expected["pageWidthPoints"], delta=tolerance)
            self.assertAlmostEqual(page["height"], expected["pageHeightPoints"], delta=tolerance)
            self.assertLess(page["width"], page["height"], msg="expected portrait")

    def test_text_structure(self):
        bundle = self._parse()
        expected = self.expected["expected"]
        counts = bundle["report"]["counts"]
        callbacks = bundle["report"]["callbackCounts"]
        self.assertEqual(callbacks.get("startTextObject", 0), expected["textFrameCallbacks"])
        self.assertEqual(counts["paragraphs"], expected["paragraphs"])
        self.assertEqual(counts["runs"], expected["styledSpans"])
        self.assertEqual(counts["textInsertions"], expected["textInsertions"])

        substantive = 0
        for page in bundle["document"]["pages"]:
            for element in page["elements"]:
                if element["type"] != "text":
                    continue
                if any(run["text"].strip()
                       for paragraph in element["paragraphs"]
                       for run in paragraph["runs"]):
                    substantive += 1
        self.assertEqual(substantive, expected["substantiveTextFrames"])

    def test_the_table_is_recovered(self):
        bundle = self._parse()
        expected = self.expected["expected"]
        tables = [element
                  for page in bundle["document"]["pages"]
                  for element in page["elements"] if element["type"] == "table"]
        self.assertEqual(len(tables), expected["tables"])
        self.assertEqual(len(tables[0]["table"]["columns"]), expected["tableColumns"])
        self.assertEqual(len(tables[0]["table"]["rows"]), expected["tableRows"])

    def test_images_and_assets(self):
        bundle = self._parse()
        expected = self.expected["expected"]
        assets = bundle["assets"]["assets"]
        self.assertEqual(len(assets), expected["distinctAssets"])
        self.assertEqual(bundle["report"]["counts"]["assetPlacements"],
                         expected["imagePlacements"])
        by_type = {}
        for asset in assets:
            by_type[asset["mimeType"]] = by_type.get(asset["mimeType"], 0) + 1
        self.assertEqual(by_type.get("image/png", 0), expected["pngAssets"])
        self.assertEqual(by_type.get("image/jpeg", 0), expected["jpegAssets"])

        reused = [asset for asset in assets
                  if len({use["pageIndex"] for use in asset["uses"]}) > 1]
        self.assertEqual(len(reused), expected["assetsUsedOnTwoPages"])
        # Deduplication is the point: one file on disk per distinct payload.
        self.assertEqual(len(bundle["_assetFiles"]), len(assets))

    def test_images_arrive_by_the_bitmap_fill_route(self):
        # The finding that drove the design. If this ever fails because
        # every image came through drawGraphicObject instead, that is new
        # evidence about the format, not a broken test.
        bundle = self._parse()
        routes = {use["route"]
                  for asset in bundle["assets"]["assets"] for use in asset["uses"]}
        self.assertIn("bitmapFillShape", routes)

    def test_paths_and_rendering_wrappers(self):
        bundle = self._parse()
        expected = self.expected["expected"]
        callbacks = bundle["report"]["callbackCounts"]
        self.assertEqual(callbacks.get("drawPath", 0), expected["pathCallbacks"])
        wrappers = [element
                    for page in bundle["document"]["pages"]
                    for element in page["elements"] if element["type"] == "wrapper"]
        self.assertEqual(len(wrappers), expected["renderingLayerWrappers"])
        for wrapper in wrappers:
            self.assertFalse(wrapper["container"]["isAuthoredGroup"])

    def test_fonts(self):
        bundle = self._parse()
        families = sorted(font["family"] for font in bundle["document"]["fonts"] if font["family"])
        self.assertEqual(families, sorted(self.expected["expected"]["fonts"]))

    def test_nothing_was_truncated(self):
        bundle = self._parse()
        self.assertFalse(bundle["document"]["truncation"]["truncated"])
        self.assertEqual(bundle["report"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
