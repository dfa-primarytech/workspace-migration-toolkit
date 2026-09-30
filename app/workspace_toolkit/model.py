from collections import Counter
from enum import StrEnum

# Marks a character in source text that cannot be compared: a Word symbol
# (w:sym) names a code in its font, not a character, so what the converted file
# shows for it is not known. A word holding one is left out of the text check.
# NUL cannot occur in XML text, so it never collides with real content.
UNCOMPARABLE = "\x00"

# Hyphens that read the same but are different characters on each side: Word's
# no-break hyphen, Google's export of it, a plain hyphen. A soft hyphen shows
# only where a line breaks, so it is not part of the word at all.
_SAME_TEXT = str.maketrans({"‐": "-", "‑": "-", "­": None})


class Compatibility(StrEnum):
    NATIVE = "NATIVE"
    SUBSTITUTED = "SUBSTITUTED"
    FLATTENED = "FLATTENED"
    UNSUPPORTED = "UNSUPPORTED"
    IGNORED = "IGNORED"


def emu_to_points(value: str | int) -> float:
    return int(value) / 12700


def warning(code: str, message: str, **context: object) -> dict:
    return {"code": code, "message": message, **context}


def text_tokens(text: str) -> Counter[str]:
    """The words of `text`, as both sides of a text check compare them.

    Used for the source and for what Google read back alike, so a difference
    in how each spells the same visible text is not reported as text missing
    (#122). Words holding UNCOMPARABLE are dropped: nothing can be said about
    them either way.
    """
    return Counter(word for word in text.translate(_SAME_TEXT).split() if UNCOMPARABLE not in word)
