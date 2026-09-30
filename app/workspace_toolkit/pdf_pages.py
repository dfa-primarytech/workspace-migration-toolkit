"""How many pages a PDF has, and which look blank (#53).

Only as much PDF as a page count and a blank-page test need: the page tree,
and each page's content stream searched for anything that draws text or a
picture. It never extracts or keeps text. The PDF is one Google exported from
a document this app just created, but it is still read defensively: sizes are
capped, only Flate compression is decoded, and anything unexpected gives no
answer rather than a guess.

A page is "probably blank" when its content draws no text and no picture.
That is evidence for a person to look at, not proof: a page could draw only
lines, or draw text in a way this doesn't recognise.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

# Drive's own export limit is 10 MB; anything much larger is not what we asked for.
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_STREAM_BYTES = 16 * 1024 * 1024
MAX_PAGES = 5000
MAX_TREE_DEPTH = 32

OBJECT = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
STREAM = re.compile(rb"stream\r?\n")
REFERENCE = re.compile(rb"(\d+)\s+\d+\s+R")
TYPE_PAGE = re.compile(rb"/Type\s*/Page(?![A-Za-z])")
TYPE_PAGES = re.compile(rb"/Type\s*/Pages\b")
TYPE_OBJSTM = re.compile(rb"/Type\s*/ObjStm\b")
# Text-showing operators, a drawn XObject (pictures), and an inline image.
DRAWS = re.compile(rb"(?:^|[\s\]\)>])(?:Tj|TJ|'|\"|Do|BI)(?=[\s\[\(</]|$)")


@dataclass
class PdfPages:
    pages: int
    probably_blank: list[int] = field(default_factory=list)


@dataclass
class _Object:
    dictionary: bytes
    stream: bytes | None = None


def inspect_pdf(data: bytes) -> PdfPages | None:
    """The page count and probably-blank pages (numbered from 1), or None."""
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF-") or b"/Encrypt" in data:
        return None
    try:
        objects = _objects(data)
        root = _root(data, objects)
        if root is None:
            return None
        catalog = objects.get(root)
        pages_root = _reference(catalog.dictionary, b"Pages") if catalog else None
        if pages_root is None:
            return None
        order = _page_order(objects, pages_root)
    except (ValueError, zlib.error, IndexError):
        return None
    if not order:
        return None
    blank = [number for number, page in enumerate(order, 1) if _draws_nothing(objects, page)]
    return PdfPages(len(order), blank)


def _objects(data: bytes) -> dict[int, _Object]:
    """Every indirect object, including those packed into object streams."""
    found: dict[int, _Object] = {}
    for match in OBJECT.finditer(data):
        number = int(match.group(1))
        end = data.find(b"endobj", match.end())
        if end < 0:
            raise ValueError("unterminated object")
        body = data[match.end() : end]
        opened = STREAM.search(body)
        if opened is None:
            found[number] = _Object(body.strip())
            continue
        closed = body.rfind(b"endstream")
        if closed < opened.end():
            raise ValueError("unterminated stream")
        stream = body[opened.end() : closed].rstrip(b"\r\n")
        found[number] = _Object(body[: opened.start()].strip(), stream)
    for packed in list(found.values()):
        if packed.stream is not None and TYPE_OBJSTM.search(packed.dictionary):
            found.update(_unpacked(packed))
    return found


def _unpacked(packed: _Object) -> dict[int, _Object]:
    content = _decoded(packed)
    count = _integer(packed.dictionary, b"N")
    first = _integer(packed.dictionary, b"First")
    if content is None or count is None or first is None:
        raise ValueError("unreadable object stream")
    numbers = [int(n) for n in content[:first].split()]
    if len(numbers) != 2 * count:
        raise ValueError("object stream header does not match its count")
    pairs = list(zip(numbers[0::2], numbers[1::2], strict=True))
    unpacked = {}
    for index, (number, offset) in enumerate(pairs):
        end = pairs[index + 1][1] if index + 1 < len(pairs) else len(content) - first
        unpacked[number] = _Object(content[first + offset : first + end].strip())
    return unpacked


def _root(data: bytes, objects: dict[int, _Object]) -> int | None:
    trailer = data.rfind(b"/Root")
    if trailer >= 0:
        match = REFERENCE.match(data, trailer + len(b"/Root"))
        if match is None:
            match = REFERENCE.search(data[trailer : trailer + 40])
        if match is not None:
            return int(match.group(1))
    for number, found in objects.items():
        if re.search(rb"/Type\s*/Catalog\b", found.dictionary):
            return number
    return None


def _page_order(objects: dict[int, _Object], start: int) -> list[int]:
    """Page objects in reading order, walking the page tree depth first."""
    order: list[int] = []
    seen: set[int] = set()

    def walk(number: int, depth: int) -> None:
        if number in seen or depth > MAX_TREE_DEPTH or len(order) > MAX_PAGES:
            raise ValueError("page tree too deep, too large or cyclic")
        seen.add(number)
        node = objects.get(number)
        if node is None:
            raise ValueError("page tree refers to a missing object")
        if TYPE_PAGES.search(node.dictionary):
            for kid in _references(objects, node.dictionary, b"Kids"):
                walk(kid, depth + 1)
        elif TYPE_PAGE.search(node.dictionary):
            order.append(number)
        else:
            raise ValueError("page tree node is neither a page nor pages")

    walk(start, 0)
    return order


def _draws_nothing(objects: dict[int, _Object], page: int) -> bool:
    node = objects[page]
    streams = _references(objects, node.dictionary, b"Contents")
    for number in streams:
        content = objects.get(number)
        decoded = _decoded(content) if content is not None else None
        if decoded is None:
            return False  # can't tell, so not called blank
        if DRAWS.search(decoded):
            return False
    return True


def _decoded(found: _Object) -> bytes | None:
    if found.stream is None:
        return None
    filters = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", found.dictionary)
    names = re.findall(rb"/(\w+)", filters.group(1)) if filters else []
    if not names:
        return found.stream
    if names != [b"FlateDecode"] or b"/DecodeParms" in found.dictionary:
        return None
    inflater = zlib.decompressobj()
    decoded = inflater.decompress(found.stream, MAX_STREAM_BYTES)
    if inflater.unconsumed_tail:
        return None  # larger than we will inflate
    return decoded


def _integer(dictionary: bytes, key: bytes) -> int | None:
    match = re.search(rb"/" + key + rb"\s+(\d+)(?!\s+\d+\s+R)", dictionary)
    return int(match.group(1)) if match else None


def _reference(dictionary: bytes, key: bytes) -> int | None:
    match = re.search(rb"/" + key + rb"\s+(\d+)\s+\d+\s+R", dictionary)
    return int(match.group(1)) if match else None


def _references(objects: dict[int, _Object], dictionary: bytes, key: bytes) -> list[int]:
    """A key's value as object numbers: one reference, an array of them, or a
    reference to such an array."""
    array = re.search(rb"/" + key + rb"\s*\[([^\]]*)\]", dictionary)
    if array is not None:
        return [int(n) for n in REFERENCE.findall(array.group(1))]
    single = _reference(dictionary, key)
    if single is None:
        return []
    target = objects.get(single)
    if target is not None and target.stream is None and target.dictionary.startswith(b"["):
        return [int(n) for n in REFERENCE.findall(target.dictionary)]
    return [single]
