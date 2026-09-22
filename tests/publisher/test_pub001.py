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
        self.assertEqual(document["source"]["containerType"], "ole2")
        self.assertEqual(document["source"]["formatFamily"], "microsoft-publisher")
        self.assertTrue(document["source"]["supportedByParser"])
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

    def test_the_document_parses_without_a_single_diagnostic(self):
        # A clean stream: no unbalanced callbacks, no implicit containers,
        # nothing the adapter had to guess at. If this ever starts
        # reporting diagnostics, the adapter and libmspub have diverged.
        bundle = self._parse()
        self.assertEqual(
            [(d["code"], d["severity"]) for d in bundle["report"]["diagnostics"]], [])
        self.assertEqual(bundle["report"]["counts"]["callbacks"],
                         self.expected["expected"]["callbacks"])

    def test_no_image_arrives_by_draw_graphic_object(self):
        # The evidence the whole bitmap-fill route exists for: this
        # document never calls drawGraphicObject. A parser watching only
        # that callback would report a newsletter with no pictures in it.
        bundle = self._parse()
        callbacks = bundle["report"]["callbackCounts"]
        expected = self.expected["expected"]
        self.assertEqual(callbacks.get("drawGraphicObject", 0),
                         expected["drawGraphicObjectCallbacks"])
        self.assertEqual(callbacks.get("drawPolygon", 0), expected["drawPolygonCallbacks"])
        routes = {use["route"]
                  for asset in bundle["assets"]["assets"] for use in asset["uses"]}
        self.assertEqual(routes, {"bitmapFillShape"})

    def test_every_image_placement_is_rectangular(self):
        bundle = self._parse()
        rectangular = all(use["polygonIsRectangular"]
                          for asset in bundle["assets"]["assets"] for use in asset["uses"])
        self.assertEqual(rectangular,
                         self.expected["expected"]["allImagePlacementsRectangular"])

    def test_element_type_tally(self):
        bundle = self._parse()
        counts = bundle["report"]["counts"]
        expected = self.expected["expected"]
        self.assertEqual(counts["elements"], expected["elements"])
        self.assertEqual(counts["wrapperElements"], expected["wrapperElements"])
        self.assertEqual(counts["pathElements"], expected["pathElements"])
        self.assertEqual(counts["shapeElements"], expected["shapeElements"])
        self.assertEqual(counts["masterPages"], expected["masterPages"])
        # Nothing fell through to the unknown bucket.
        self.assertEqual(counts["unknownElements"], expected["unknownElements"])

    def test_compatibility_candidate_tally(self):
        bundle = self._parse()
        actual = {key: value
                  for key, value in bundle["report"]["compatibility"].items() if key != "basis"}
        self.assertEqual(actual, self.expected["expected"]["compatibilityCandidates"])
        self.assertEqual(bundle["report"]["compatibility"]["basis"], "parser-candidate")

    def _runs(self, bundle):
        for page in bundle["document"]["pages"]:
            for element in page["elements"]:
                for paragraph in element.get("paragraphs", []):
                    yield paragraph, element
                for row in element.get("table", {}).get("rows", []):
                    for cell in row["cells"]:
                        for paragraph in cell["paragraphs"]:
                            yield paragraph, element

    def test_character_formatting_is_recovered(self):
        bundle = self._parse()
        expected = self.expected["expected"]
        runs = [run for paragraph, _ in self._runs(bundle) for run in paragraph["runs"]]
        self.assertEqual(len(runs), expected["styledSpans"])
        self.assertEqual(sum(1 for r in runs if r["style"]["bold"]), expected["boldRuns"])
        self.assertEqual(sum(1 for r in runs if r["style"]["italic"]), expected["italicRuns"])
        self.assertEqual(sum(1 for r in runs if r["style"]["underline"]),
                         expected["underlinedRuns"])
        # Every run carries a resolved font, size, colour and language.
        for key in ("fontFamily", "fontSizePoints", "color", "language"):
            self.assertEqual(sum(1 for r in runs if r["style"][key] is not None), len(runs),
                             msg=f"not every run carried {key}")
        self.assertEqual(sorted({r["style"]["fontSizePoints"] for r in runs}),
                         expected["fontSizesPoints"])
        self.assertEqual(sorted({r["style"]["color"] for r in runs}), expected["textColours"])

    def test_paragraph_alignment_is_recovered(self):
        bundle = self._parse()
        tally = {}
        for paragraph, _ in self._runs(bundle):
            for _run in paragraph["runs"]:
                alignment = paragraph["style"]["alignment"]
                tally[alignment] = tally.get(alignment, 0) + 1
        self.assertEqual(tally, self.expected["expected"]["paragraphAlignments"])

    def test_explicit_spaces_and_breaks_survive_as_their_own_items(self):
        # 143 explicit spaces. Collapsing them into the text string would
        # lose the distinction between typed and explicit whitespace.
        bundle = self._parse()
        expected = self.expected["expected"]
        kinds = {}
        for paragraph, _ in self._runs(bundle):
            for run in paragraph["runs"]:
                for item in run["items"]:
                    kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        self.assertEqual(kinds.get("space", 0), expected["explicitSpaces"])
        self.assertEqual(kinds.get("lineBreak", 0), expected["lineBreaks"])
        self.assertEqual(kinds.get("text", 0), expected["textInsertions"])

    def test_the_table_reports_that_no_row_height_was_declared(self):
        bundle = self._parse()
        expected = self.expected["expected"]
        table = next(element
                     for page in bundle["document"]["pages"]
                     for element in page["elements"] if element["type"] == "table")
        self.assertAlmostEqual(table["table"]["columns"][0]["width"]["points"],
                               expected["tableColumnWidthPoints"], places=3)
        self.assertEqual([len(cell["paragraphs"])
                          for row in table["table"]["rows"] for cell in row["cells"]],
                         expected["tableCellParagraphs"])
        declared = any(row["height"] is not None for row in table["table"]["rows"])
        self.assertEqual(declared, expected["tableRowHeightsDeclared"])
        if not declared:
            self.assertIn("table-row-heights-unknown",
                          [note["code"] for note in table["warnings"]])

    def test_font_usage_counts(self):
        bundle = self._parse()
        actual = {font["family"]: font["usageCount"] for font in bundle["document"]["fonts"]}
        self.assertEqual(actual, self.expected["expected"]["fontUsageCounts"])

    def test_non_substantive_frames_are_kept_not_dropped(self):
        # Two frames hold a single character each. They are layout
        # placeholders; dropping them would shift the page.
        bundle = self._parse()
        expected = self.expected["expected"]
        frames = [element
                  for page in bundle["document"]["pages"]
                  for element in page["elements"] if element["type"] == "text"]
        empty = [f for f in frames
                 if not any(run["text"].strip()
                            for paragraph in f["paragraphs"] for run in paragraph["runs"])]
        self.assertEqual(len(empty), expected["nonSubstantiveTextFrames"])
        self.assertEqual(len(frames), expected["textFrameCallbacks"])

    def test_output_is_deterministic_for_this_document(self):
        first = self._parse()
        second = self._parse()
        for name in ("document", "assets"):
            self.assertEqual(json.dumps(first[name], sort_keys=False),
                             json.dumps(second[name], sort_keys=False))


if __name__ == "__main__":
    unittest.main()
