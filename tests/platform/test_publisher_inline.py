"""Pictures set inline in Publisher text (PUB-002's book covers in table cells),
which libmspub leaves out: recovered from the drawing records and placed over
their cells. The records are built here; nothing comes from a real file."""

from __future__ import annotations

import io
import struct

from PIL import Image
from workspace_toolkit.publisher_art import Prepared
from workspace_toolkit.publisher_inline import MARK, marks, picture_bytes, prepared, read

from .test_publisher_crop import container, record
from .test_publisher_slides import document, element, paragraph, planned, report, requests, run

EMU = 12700


def fbse(size: int, delay: int) -> bytes:
    body = bytearray(36)
    struct.pack_into("<III", body, 20, size, 1, delay)
    return record(0xF007, bytes(body))


def blocks(*values: tuple[int, int, int]) -> bytes:
    """Publisher's numbered values: a length, then (id, type, value) each."""
    body = b"".join(struct.pack("<BBI", i, t, v) for i, t, v in values)
    return struct.pack("<I", 4 + len(body)) + body


def inline_shape(blip: int, seq: int, width: float, height: float, margin=2.88) -> bytes:
    left = round(margin * EMU)
    anchor = blocks(
        (1, 0x20, left),
        (2, 0x20, left),
        (3, 0x20, left + round(width * EMU)),
        (4, 0x20, left + round(height * EMU)),
    )
    return container(
        0xF004,
        record(0xF00A, struct.pack("<II", 1025 + seq, 0xA00), instance=1),
        record(0xF00B, struct.pack("<HI", 0x4104, blip), instance=1),
        record(0xF010, anchor),
        record(0xF011, blocks((1, 0x68, seq))),
    )


def jpeg(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (20, 90, 160)).save(out, "JPEG")
    return out.getvalue()


def stored(payload: bytes) -> bytes:
    """A stored JPEG as Publisher keeps it: one UID and a tag byte first."""
    return record(0xF01D, bytes(16) + b"\xff" + payload, instance=0x46A)


def files(tmp_path, shapes: list[bytes], payloads: list[bytes]):
    pictures, offsets = b"", []
    for payload in payloads:
        offsets.append(len(pictures))
        pictures += stored(payload)
    sizes = [len(stored(p)) for p in payloads]
    dgg = container(
        0xF000,
        record(0xF006, bytes(16)),
        container(0xF001, *(fbse(s, o) for s, o in zip(sizes, offsets, strict=True))),
    )
    dg = container(0xF002, record(0xF008, bytes(8)), container(0xF003, *shapes))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "drawing.bin").write_bytes(dgg + b"\0\0\0\0" + dg + b"\0\0\0\0")
    (bundle / "drawing-pictures.bin").write_bytes(pictures)
    return bundle


def cover_table(eid: str, *covered: int) -> dict:
    """A one-row table whose listed columns each hold a title, then a cover."""

    def cell(column: int) -> dict:
        paragraphs = [paragraph(run(f"Book {column}"), align="center")]
        if column in covered:
            paragraphs.append(paragraph(run(MARK), align="center"))
        return {
            "row": 0,
            "column": column,
            "rowSpan": 1,
            "columnSpan": 1,
            "covered": False,
            "paragraphs": paragraphs,
        }

    columns = [{"width": {"points": 100}} for _ in range(3)]
    rows = [{"index": 0, "cells": [cell(c) for c in range(3)]}]
    return element(eid, "table", 0, (50, 40, 300, 120), table={"columns": columns, "rows": rows})


def test_picture_shapes_are_read_with_their_size_and_sequence():
    blob = container(
        0xF000,
        record(0xF006, bytes(16)),
        container(0xF001, fbse(1000, 0), fbse(2000, 1000)),
    )
    blob += b"\0\0\0\0" + container(
        0xF002,
        record(0xF008, bytes(8)),
        container(0xF003, inline_shape(2, 392, 33.6, 51.6)),
    )
    store, shapes = read(blob + b"\0\0\0\0")
    assert [(s.size, s.offset) for s in store] == [(1000, 0), (2000, 1000)]
    (shape,) = shapes
    assert (shape.seq, shape.blip) == (392, 2)
    # left and top are the cell's margin; the size is what lies between
    assert abs(shape.width - 33.6) < 0.01 and abs(shape.height - 51.6) < 0.01


def test_a_stored_jpeg_is_handed_on_as_its_own_file():
    payload = jpeg(8, 12)
    data = b"junk" + stored(payload)
    assert picture_bytes(data, 4) == (payload, "image/jpeg")
    assert picture_bytes(data, 0) is None  # not a record at all
    assert picture_bytes(data[:-3], 4) is None  # claims more than there is


def test_marks_come_in_reading_order():
    doc = document([cover_table("el_1", 0, 2)], [cover_table("el_2", 1)])
    assert list(marks(doc)) == [("el_1", 0, 0, 1), ("el_1", 0, 2, 1), ("el_2", 0, 1, 1)]


def test_covers_are_paired_with_marks_by_sequence_and_placed_over_their_cells(tmp_path):
    doc = document([cover_table("el_1", 0, 2)])
    # Drawn in the other order: the sequence numbers say which comes first.
    shapes = [inline_shape(2, 20, 30, 45), inline_shape(1, 10, 40, 50)]
    bundle = files(tmp_path, shapes, [jpeg(40, 50), jpeg(30, 45)])
    found, notes = prepared(bundle, doc, {"assets": []}, tmp_path / "art")
    assert notes == []
    assert [(p.width, p.height) for p, _ in found[("el_1", 0, 0, 1)]] == [(40, 50)]
    assert [(p.width, p.height) for p, _ in found[("el_1", 0, 2, 1)]] == [(30, 45)]

    result = planned(doc, Prepared(inline=found))
    images = requests(result, "createImage")
    assert len(images) == 2
    # Over the table: made after it, so drawn on top.
    kinds = [next(iter(r)) for r in result.pages[0]]
    assert kinds.index("createTable") < kinds.index("createImage")
    # Centred in its 100 pt column, below the title's line.
    first = images[0]["elementProperties"]
    width = first["size"]["width"]["magnitude"] * first["transform"]["scaleX"]
    assert abs(first["transform"]["translateX"] - (50 + (100 - 40) / 2)) < 0.5
    assert abs(width - 40) < 0.5
    assert first["transform"]["translateY"] > 40 + 10
    # The mark is gone from the text, and its line leaves room for the cover.
    texts = [t["text"] for t in requests(result, "insertText")]
    assert all(MARK not in t for t in texts)
    rooms = [
        p["style"]["spaceAbove"]["magnitude"]
        for p in requests(result, "updateParagraphStyle")
        if "spaceAbove" in p["style"]
    ]
    assert sorted(rooms) == [45, 50]
    codes = [n["code"] for n in report(result)["el_1"]["notes"]]
    assert "inline-picture-over-table" in codes


def test_covers_that_do_not_pair_up_are_reported_not_guessed(tmp_path):
    doc = document([cover_table("el_1", 0, 1, 2)])
    bundle = files(tmp_path, [inline_shape(1, 10, 40, 50)], [jpeg(40, 50)])
    found, notes = prepared(bundle, doc, {"assets": []}, tmp_path / "art")
    assert found == {}
    assert [n["code"] for n in notes] == ["inline-pictures-unplaced"]
    # The marks still never reach Slides.
    result = planned(doc, Prepared())
    assert all(MARK not in t["text"] for t in requests(result, "insertText"))


def test_a_picture_the_reader_extracted_is_not_taken_for_an_inline_one(tmp_path):
    doc = document([cover_table("el_1", 0)])
    # Sizes far apart, as the store is matched to the reader's assets by size.
    payloads = [jpeg(40, 50), jpeg(30, 45) + bytes(500)]
    shapes = [inline_shape(1, 10, 40, 50), inline_shape(2, 20, 30, 45)]
    bundle = files(tmp_path, shapes, payloads)
    placed = {"id": "a", "byteLength": len(stored(payloads[1]))}  # the second was extracted
    found, notes = prepared(bundle, doc, {"assets": [placed]}, tmp_path / "art")
    assert notes == []
    assert [(p.width, p.height) for p, _ in found[("el_1", 0, 0, 1)]] == [(40, 50)]
