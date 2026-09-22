"""End-to-end tests for the publisher-parser CLI.

These need the native binary built; they skip cleanly when it is not.
None of them touches a Google API, and none needs a .pub file: the
failure paths are exercised with bytes that are definitively not
Publisher documents, which is exactly what a hostile upload looks like.
"""

from __future__ import annotations

import json
import os
import unittest

import harness


class CliTest(unittest.TestCase):
    def setUp(self):
        self.parser = harness.require_parser(self)

    def _write(self, directory: str, name: str, payload: bytes) -> str:
        path = os.path.join(directory, name)
        os.makedirs(directory, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def test_version_reports_the_libraries_it_was_built_against(self):
        run = harness.run_parser(self.parser, "--version", "")
        # --version short-circuits before the positional arguments matter.
        self.assertEqual(run.returncode, 0)
        self.assertIn("publisher-parser", run.stdout)
        self.assertIn("libmspub", run.stdout)
        self.assertIn("librevenge", run.stdout)
        self.assertIn("schema", run.stdout)

    def test_a_non_publisher_file_is_refused_with_a_report(self):
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "junk.pub", b"definitely not publisher")
            run = harness.run_parser(self.parser, source, out)
            self.assertEqual(run.returncode, 2)
            # A refusal still produces a machine-readable answer, so a
            # caller never has to parse an exit code alone.
            with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["failureCode"], "unsupported-document")
            self.assertFalse(report["source"]["supportedByParser"])
            self.assertEqual(report["source"]["filename"], "junk.pub")

    def test_the_report_records_the_source_hash_and_length(self):
        payload = b"definitely not publisher"
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "junk.pub", payload)
            harness.run_parser(self.parser, source, out)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual(report["source"]["sha256"], harness.sha256_file(source))
            self.assertEqual(report["source"]["byteLength"], len(payload))

    def test_only_the_basename_reaches_the_bundle(self):
        # The directory a file was processed in is often a person's name.
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "junk.pub", b"nope")
            harness.run_parser(self.parser, source, out)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn(os.path.dirname(source), text)

    def test_an_ole_container_that_is_not_publisher_is_still_identified(self):
        ole = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1]) + b"\x00" * 512
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "other.pub", ole)
            harness.run_parser(self.parser, source, out)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual(report["source"]["containerType"], "ole2")
            self.assertEqual(report["status"], "failed")

    def test_an_empty_file_is_refused(self):
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "empty.pub", b"")
            run = harness.run_parser(self.parser, source, out)
            self.assertEqual(run.returncode, 2)
            self.assertIn("input-empty", run.stderr)

    def test_a_missing_file_is_refused(self):
        with harness.TempOutput() as out:
            run = harness.run_parser(self.parser, os.path.join(out, "absent.pub"), out)
            self.assertEqual(run.returncode, 2)
            self.assertIn("input-unreadable", run.stderr)

    def test_an_oversized_input_is_refused_before_parsing(self):
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "big.pub", b"x" * 4096)
            run = harness.run_parser(self.parser, source, out, "--max-input-bytes", "1024")
            self.assertEqual(run.returncode, 2)
            self.assertIn("input-too-large", run.stderr)

    def test_a_non_empty_output_directory_is_refused_without_force(self):
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "junk.pub", b"nope")
            harness.run_parser(self.parser, source, out)
            second = harness.run_parser(self.parser, source, out)
            self.assertIn("output-not-empty", second.stderr)
            forced = harness.run_parser(self.parser, source, out, "--force")
            self.assertNotIn("output-not-empty", forced.stderr)

    def test_no_scratch_files_are_left_behind(self):
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "junk.pub", b"nope")
            harness.run_parser(self.parser, source, out)
            leftovers = [name for name in os.listdir(out) if ".tmp-" in name]
            self.assertEqual(leftovers, [])

    def test_failure_output_carries_no_document_bytes(self):
        # Operational output must never echo content from an input file.
        marker = b"CONFIDENTIAL-PUPIL-RECORD"
        with harness.TempOutput() as out:
            source = self._write(os.path.dirname(out), "junk.pub", marker * 4)
            run = harness.run_parser(self.parser, source, out)
            self.assertNotIn(marker.decode(), run.stdout)
            self.assertNotIn(marker.decode(), run.stderr)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
                self.assertNotIn(marker.decode(), handle.read())

    def test_an_unknown_option_is_refused(self):
        with harness.TempOutput() as out:
            run = harness.run_parser(self.parser, "--not-an-option", out)
            self.assertEqual(run.returncode, 2)


if __name__ == "__main__":
    unittest.main()
