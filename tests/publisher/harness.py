"""Shared helpers for the Publisher parser's Python tests.

Everything here runs without a network, without Google credentials and
without any third-party package. The private PUB-001 fixture is reached
through an environment variable and is never read from the repository:
it is a real school document and must not be committed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MODEL_DIR = os.path.join(REPO_ROOT, "packages", "document-model")
FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "publisher")


def _load_document_model() -> types.ModuleType:
    """Imports packages/document-model/validation.py.

    PROJECT.md names the directory ``document-model``, and a hyphen is not
    a legal module name, so the module is loaded by path rather than by
    renaming the directory the architecture document specifies.
    """
    name = "document_model_validation"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(MODEL_DIR, "validation.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validation = _load_document_model()

# Where a private fixture is supplied from. Never a path inside the repo.
PUB001_ENV = "PUBLISHER_FIXTURE_PUB001"
# Overrides where the built binary is found, for a container or a CI job
# that builds somewhere other than the default.
PARSER_ENV = "PUBLISHER_PARSER_BIN"

DEFAULT_PARSER = os.path.join(REPO_ROOT, "native", "pub-parser", "build", "publisher-parser")

# Hard ceiling on any parser subprocess. The parser's own --max-seconds is
# a backstop inside the callback sink; a hang before the first callback
# would never reach it, so the real timeout lives out here at the
# invoking boundary.
PARSER_TIMEOUT_SECONDS = 120


def parser_path() -> str | None:
    candidate = os.environ.get(PARSER_ENV) or DEFAULT_PARSER
    return candidate if os.path.isfile(candidate) and os.access(candidate, os.X_OK) else None


def require_parser(test: unittest.TestCase) -> str:
    path = parser_path()
    if path is None:
        test.skipTest(f"publisher-parser is not built; build native/pub-parser or set {PARSER_ENV}")
    return path


def pub001_path() -> str | None:
    path = os.environ.get(PUB001_ENV)
    return path if path and os.path.isfile(path) else None


def require_pub001(test: unittest.TestCase) -> str:
    path = pub001_path()
    if path is None:
        test.skipTest(
            f"the private PUB-001 fixture is not available; set {PUB001_ENV} to its path. "
            "It is a real school document and is never committed."
        )
    return path


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ParserRun:
    def __init__(self, returncode: int, stdout: str, stderr: str, output_dir: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.output_dir = output_dir


def run_parser(parser: str, source: str, output_dir: str, *extra: str) -> ParserRun:
    # S603 reviewed: an argument list, never a shell. The executable is the
    # in-repo build or PUBLISHER_PARSER_BIN, set by CI or the developer and
    # checked by parser_path(); every argument is chosen by the test. The
    # untrusted input is the document's content, which the parser reads as
    # data -- nothing in it selects what is executed.
    completed = subprocess.run(  # noqa: S603
        [parser, *extra, source, output_dir],
        capture_output=True,
        text=True,
        timeout=PARSER_TIMEOUT_SECONDS,
        check=False,
    )
    return ParserRun(completed.returncode, completed.stdout, completed.stderr, output_dir)


class TempOutput:
    """A scratch output directory that removes itself.

    A test that extracts assets from a real document must not leave them
    on the machine afterwards.
    """

    def __enter__(self) -> str:
        self._dir = tempfile.TemporaryDirectory(prefix="pubir-test-")
        return os.path.join(self._dir.name, "out")

    def __exit__(self, *exc) -> None:
        self._dir.cleanup()
