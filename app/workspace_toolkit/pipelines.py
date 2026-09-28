"""Which parser, report and renderer a given upload goes through.

One registry so the request path has a single `if` -- resolving the format --
rather than a branch at every step. Adding a format means adding an entry here
and the modules it names, not editing the web layer again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import docs, docx, google, pptx, publisher
from .errors import ToolkitError
from .package import DOCX, PPTX, PUB, Format

SUPPORTED = ".pptx, .docx and .pub"


@dataclass(frozen=True)
class Pipeline:
    fmt: Format
    analysis_report: Callable[[dict], dict]
    convert: Callable[..., Awaitable[dict]]
    kind: str  # what the output is, for the report
    destination: str  # where it ends up, for people
    convertible: bool = True  # False while a format can be checked but not converted

    @property
    def source_name(self) -> str:
        """Filename used inside the job directory. Never the user's own name."""
        return "source" + self.fmt.suffix


PIPELINES: dict[str, Pipeline] = {
    ".pptx": Pipeline(
        fmt=PPTX,
        analysis_report=pptx.analysis_report,
        convert=google.convert,
        kind="presentation",
        destination="Google Slides",
    ),
    ".docx": Pipeline(
        fmt=DOCX,
        analysis_report=docx.analysis_report,
        convert=docs.convert,
        kind="document",
        destination="Google Docs",
    ),
    ".pub": Pipeline(
        fmt=PUB,
        analysis_report=publisher.analysis_report,
        convert=publisher.convert,
        kind="presentation",
        destination="Google Slides",
        convertible=False,  # the Slides renderer is the next step (DECISIONS.md)
    ),
}


def resolve(filename: str) -> Pipeline:
    pipeline = PIPELINES.get(Path(filename).suffix.lower())
    if pipeline is None:
        raise ToolkitError("unsupported_type", f"Only {SUPPORTED} files are supported here.")
    return pipeline


def describe() -> list[dict[str, Any]]:
    """What the browser needs to know about the formats on offer."""
    return [
        {
            "extension": suffix,
            "destination": pipeline.destination,
            "kind": pipeline.kind,
            "mime": pipeline.fmt.mime,
            "convertible": pipeline.convertible,
        }
        for suffix, pipeline in PIPELINES.items()
    ]
