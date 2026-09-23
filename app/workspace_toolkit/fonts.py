"""Shared font compatibility recommendations for every source format.

This module deliberately does not download fonts or claim that a family is
available in every Google Workspace tenant.  It records deterministic,
reviewable candidates from the Google Fonts catalogue.  Renderers decide when
and how to apply them, and conversion reports retain the original family.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FontStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    SUBSTITUTED = "SUBSTITUTED"
    UNKNOWN = "UNKNOWN"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class Substitution:
    replacement: str
    confidence: Confidence
    reason: str
    metric_compatible: bool = False
    manual_review: bool = False


# Families Google Docs ships itself. Measured on 2026-09-23 by converting a
# document naming each one, exporting the result as PDF and reading which
# fonts the renderer actually used: a family that came back under its own name
# is present, one replaced by something we never asked for is not.
#
# This matters more than it sounds. The substitution table below was built on
# the assumption that Microsoft's families are absent from Google Docs, and for
# most of them that assumption is simply false. Replacing a font Docs already
# has costs the author's choice and buys nothing -- the document arrives in a
# typeface nobody picked.
#
# Measured in one tenant. Availability can differ by Workspace edition, so this
# is evidence rather than a guarantee; a family wrongly listed here is left
# alone, which is the safe direction to be wrong in.
DOCS_NATIVE = frozenset(
    {
        "Arial",
        "Arial MT",
        "Book Antiqua",
        "Calibri",
        "Calibri Light",
        "Cambria",
        "Cambria Math",
        "Century Gothic",
        "Comic Sans MS",
        "Consolas",
        "Courier New",
        "Franklin Gothic",
        "Franklin Gothic Medium",
        "Garamond",
        "Georgia",
        "Impact",
        "Palatino Linotype",
        "Tahoma",
        "Times New Roman",
        "Times New Roman PS MT",
        "Trebuchet MS",
        "Verdana",
    }
)


# This is intentionally a compact, reviewed catalogue rather than a stale copy
# of every Google Font.  Families are added when a source mapping or fixture
# needs them.  Availability in Docs/Slides still needs live verification.
GOOGLE_FONT_CANDIDATES = frozenset(
    {
        "Andika",
        "Anton",
        "Arimo",
        "Atkinson Hyperlegible",
        "Caladea",
        "Carlito",
        "Caveat",
        "Comic Neue",
        "Cousine",
        "EB Garamond",
        "Inter",
        "Lato",
        "Lexend",
        "Libre Baskerville",
        "Libre Franklin",
        "Merriweather",
        "Montserrat",
        "Noto Sans",
        "Noto Serif",
        "Open Sans",
        "Patrick Hand",
        "Roboto",
        "Roboto Mono",
        "Roboto Slab",
        "Schoolbell",
        "Tinos",
    }
)


# Exact metric-compatible families come first.  The remaining entries preserve
# broad proportions and teaching intent, but are explicitly reviewable.
SUBSTITUTIONS: dict[str, Substitution] = {
    "aptos": Substitution("Carlito", Confidence.MEDIUM, "similar humanist Office sans serif"),
    "aptos display": Substitution(
        "Carlito", Confidence.MEDIUM, "similar humanist Office sans serif"
    ),
    "aptos narrow": Substitution(
        "Roboto", Confidence.LOW, "portable sans serif; width requires review", manual_review=True
    ),
    "segoe ui": Substitution("Inter", Confidence.MEDIUM, "similar screen-oriented sans serif"),
    "baskerville": Substitution(
        "Libre Baskerville", Confidence.HIGH, "same historical type family"
    ),
    "rockwell": Substitution("Roboto Slab", Confidence.MEDIUM, "slab serif"),
    "bradley hand itc": Substitution(
        "Patrick Hand", Confidence.MEDIUM, "informal classroom handwriting"
    ),
    "segoe print": Substitution(
        "Patrick Hand", Confidence.MEDIUM, "informal classroom handwriting"
    ),
    "lucida handwriting": Substitution("Caveat", Confidence.MEDIUM, "casual handwriting"),
    "chalkboard": Substitution("Schoolbell", Confidence.MEDIUM, "school display handwriting"),
    "chalkboard se": Substitution("Schoolbell", Confidence.MEDIUM, "school display handwriting"),
    "chalkduster": Substitution("Schoolbell", Confidence.MEDIUM, "school display handwriting"),
    "sassoon primary": Substitution(
        "Andika", Confidence.MEDIUM, "literacy-focused family with clear letterforms"
    ),
    "sassoon infant": Substitution(
        "Andika", Confidence.MEDIUM, "literacy-focused family with clear letterforms"
    ),
    "twinkl": Substitution(
        "Andika",
        Confidence.LOW,
        "clear classroom letterforms; proprietary family metrics require review",
        manual_review=True,
    ),
    # Accessibility choices are recommendations only.  A human must confirm
    # that the replacement still meets the learner's needs.
    "opendyslexic": Substitution(
        "Lexend",
        Confidence.LOW,
        "reading-accessibility candidate, not a like-for-like replacement",
        manual_review=True,
    ),
    "dyslexie": Substitution(
        "Lexend",
        Confidence.LOW,
        "reading-accessibility candidate, not a like-for-like replacement",
        manual_review=True,
    ),
}


def normalise_family(family: str) -> str:
    """Normalise a family for lookup while retaining its spelling in reports."""
    return " ".join(family.strip().strip("'\"").split()).casefold()


_GOOGLE_BY_KEY = {normalise_family(name): name for name in GOOGLE_FONT_CANDIDATES}
_NATIVE_BY_KEY = {normalise_family(name): name for name in DOCS_NATIVE}


def compatibility(family: str) -> dict[str, object]:
    """Return a deterministic recommendation without silently inventing one."""
    original = " ".join(family.strip().strip("'\"").split())
    key = normalise_family(family)
    # Checked before any substitution: a family Docs already has must never be
    # replaced, whatever mapping might once have existed for it.
    if key in _NATIVE_BY_KEY:
        return {
            "name": original,
            "status": FontStatus.AVAILABLE,
            "replacement": None,
            "confidence": Confidence.HIGH,
            "basis": "measured-present-in-google-docs",
            "workspaceAvailability": "measured-2026-09-23",
            "manualReview": False,
        }
    if key in _GOOGLE_BY_KEY:
        return {
            "name": original,
            "status": FontStatus.AVAILABLE,
            "replacement": _GOOGLE_BY_KEY[key],
            "confidence": Confidence.HIGH,
            "basis": "curated-google-fonts-catalogue",
            "workspaceAvailability": "unverified",
            "manualReview": False,
        }
    candidate = SUBSTITUTIONS.get(key)
    if candidate:
        return {
            "name": original,
            "status": FontStatus.SUBSTITUTED,
            "replacement": candidate.replacement,
            "confidence": candidate.confidence,
            "reason": candidate.reason,
            "metricCompatible": candidate.metric_compatible,
            "basis": "curated-substitution",
            "workspaceAvailability": "unverified",
            "manualReview": candidate.manual_review,
        }
    return {
        "name": original,
        "status": FontStatus.UNKNOWN,
        "replacement": None,
        "confidence": None,
        "basis": "no-reviewed-mapping",
        "workspaceAvailability": "unverified",
        "manualReview": True,
    }


def catalogue(families: set[str] | list[str]) -> list[dict[str, object]]:
    """Deduplicate families case-insensitively and return stable report order."""
    unique: dict[str, str] = {}
    for family in families:
        if family.strip():
            unique.setdefault(normalise_family(family), " ".join(family.strip().split()))
    return [compatibility(unique[key]) for key in sorted(unique)]
