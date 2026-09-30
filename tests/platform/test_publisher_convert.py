"""Sending a planned Publisher conversion (Publisher step 3), against a fake Google.

`FakeGoogle` behaves like the parts of Drive, Slides, Cloud Storage and IAM
the converter uses. It applies each batchUpdate, and it refuses a picture
unless its link is signed and its stored copy still exists. Nothing reaches
the network, and no document is real.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from workspace_toolkit import publisher_convert, storage
from workspace_toolkit.config import Settings
from workspace_toolkit.errors import ToolkitError
from workspace_toolkit.google import Google
from workspace_toolkit.publisher import render_path
from workspace_toolkit.publisher_slides import check, plan
from workspace_toolkit.storage import Bucket, Credentials, canonical, scrub

from .test_publisher_slides import document, image, paragraph, pictures, run, text_box

SIGNER = "wmt-signer@example-project.iam.gserviceaccount.com"
READY = Settings(publisher_bucket="wmt-pictures", publisher_signer=SIGNER)
A5_EMU = {
    "width": {"magnitude": 5346000, "unit": "EMU"},
    "height": {"magnitude": 7560000, "unit": "EMU"},
}


# ------------------------------------------------------------------ signing


# Google's own V4 signing conformance cases (googleapis/conformance-tests,
# storage/v1/v4_signatures.json): the canonical request and string to sign
# must match exactly for Google to accept the signature.
CONFORMANCE = [
    (
        "test-object",
        "2019-02-01T09:00:00Z",
        10,
        "00e2fb794ea93d7adb703edaebdd509821fcc7d4f1a79ac5c8d2b394df109320",  # pragma: allowlist secret -- a published SHA-256
    ),
    (
        "test-object",
        "2019-03-01T09:00:00Z",
        20,
        "779f19fdb6fd381390e2d5af04947cf21750277ee3c20e0c97b7e46a1dff8907",  # pragma: allowlist secret -- a published SHA-256
    ),
    (
        "/path/with/slashes/under_score/amper&sand/file.ext",
        "2019-02-01T09:00:00Z",
        10,
        "63c601ecd6ccfec84f1113fc906609cbdf7651395f4300cecd96ddd2c35164f8",  # pragma: allowlist secret -- a published SHA-256
    ),
]


@pytest.mark.parametrize("name, timestamp, seconds, digest", CONFORMANCE)
def test_links_are_signed_exactly_as_google_specifies(name, timestamp, seconds, digest):
    when = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    request, to_sign, _ = canonical(
        "test-bucket",
        name,
        "test-iam-credentials@dummy-project-id.iam.gserviceaccount.com",
        when,
        seconds,
    )
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    assert (
        to_sign == f"GOOG4-RSA-SHA256\n{stamp}\n{when:%Y%m%d}/auto/storage/goog4_request\n{digest}"
    )
    assert request.startswith("GET\n/test-bucket/")
    assert request.endswith("\nhost:storage.googleapis.com\n\nhost\nUNSIGNED-PAYLOAD")


class Token(Credentials):
    def __init__(self, client, value="sa-token"):
        super().__init__(client)
        self.value = value

    async def _fetch(self):
        return self.value, 3600


def test_a_signed_link_carries_googles_signature_of_the_right_string():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sa-token"
        assert unquote(request.url.path).endswith(f"/serviceAccounts/{SIGNER}:signBlob")
        payload = base64.b64decode(json.loads(request.content)["payload"])
        seen["payload"] = payload
        signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        return httpx.Response(
            200, json={"keyId": "k", "signedBlob": base64.b64encode(signature).decode()}
        )

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            bucket = Bucket("wmt-pictures", SIGNER, Token(client), client)
            return await bucket.sign("publisher/abc.png", now=datetime(2026, 9, 28, 12, tzinfo=UTC))

    url = asyncio.run(go())
    parts = urlsplit(url)
    assert (
        parts.netloc == "storage.googleapis.com" and parts.path == "/wmt-pictures/publisher/abc.png"
    )
    query = parse_qs(parts.query)
    assert query["X-Goog-Expires"] == ["900"]  # 15 minutes
    assert query["X-Goog-Credential"] == [f"{SIGNER}/20260928/auto/storage/goog4_request"]
    _, expected, _ = canonical(
        "wmt-pictures", "publisher/abc.png", SIGNER, datetime(2026, 9, 28, 12, tzinfo=UTC), 900
    )
    assert seen["payload"] == expected.encode()
    signature = bytes.fromhex(query["X-Goog-Signature"][0])
    key.public_key().verify(signature, expected.encode(), padding.PKCS1v15(), hashes.SHA256())


def test_a_signed_link_never_reaches_a_report():
    text = "failed: https://storage.googleapis.com/b/o.png?X-Goog-Algorithm=x&X-Goog-Signature=abc123 end"
    assert scrub(text) == "failed: [signed link] end"


def test_credentials_are_the_apps_own_and_never_a_key_file(tmp_path, monkeypatch):
    async def pick():
        async with httpx.AsyncClient() as client:
            return storage.credentials(client)

    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("PUBLISHER_STORAGE_TOKEN", raising=False)
    adc = tmp_path / "adc.json"
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(adc))
    adc.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "c",
                "client_secret": "s",
                "refresh_token": "r",
            }
        )
    )
    assert isinstance(asyncio.run(pick()), storage.UserCredentials)
    adc.write_text(json.dumps({"type": "service_account", "private_key": "…"}))
    with pytest.raises(ToolkitError, match="gcloud login"):
        asyncio.run(pick())
    adc.unlink()
    with pytest.raises(ToolkitError) as missing:
        asyncio.run(pick())
    assert missing.value.code == "publisher_storage_unavailable"
    monkeypatch.setenv("PUBLISHER_STORAGE_TOKEN", "short-lived")
    picked = asyncio.run(pick())
    assert isinstance(picked, storage.StaticCredentials)
    assert asyncio.run(picked.token()) == "short-lived"
    monkeypatch.setenv("K_SERVICE", "workspace-toolkit")  # Cloud Run's own account wins
    assert isinstance(asyncio.run(pick()), storage.MetadataCredentials)


# ------------------------------------------------------------------ a fake Google


class FakeGoogle:
    """Just enough of Drive, Slides, Cloud Storage and IAM to convert against."""

    def __init__(
        self,
        *,
        refuse: set[str] = frozenset(),
        page_size=A5_EMU,
        lose_reply=False,
        store_fails=lambda n: False,
    ):
        self.refuse = refuse  # objectIds whose pictures Slides "cannot fetch"
        self.store_fails = store_fails  # given the upload's number (from 1): answer 503?
        self.uploads = 0
        self.page_size = page_size
        self.lose_reply = lose_reply
        self.slides: dict[str, list[dict]] = {}
        self.order: list[str] = []
        self.objects: dict[str, dict] = {}
        self.stored: set[str] = set()
        self.ever_stored: set[str] = set()
        self.tokens: dict[str, set[str]] = {"user": set(), "app": set()}
        self.batches = 0
        self.presentations = 0
        self.saved: list[bytes] = []
        self.pending = ""  # the mimeType of the upload in progress
        self.deck: bytes = b""

    def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        token = request.headers.get("Authorization", "")
        if host in {"storage.googleapis.com", "iamcredentials.googleapis.com"}:
            self.tokens["app"].add(token)
            return self.storage(request)
        self.tokens["user"].add(token)
        if host == "slides.googleapis.com":
            return self.slides_api(request)
        if path.startswith("/upload/drive") and request.method == "POST":
            self.pending = json.loads(request.content)["mimeType"]
            return httpx.Response(
                200,
                headers={
                    "Location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=1"
                },
            )
        if path.startswith("/upload/drive") and request.method == "PUT":
            if self.pending == "application/vnd.google-apps.presentation":
                # An imported deck becomes a presentation with one slide of its own.
                self.presentations += 1
                self.deck = request.read()
                self.slides = {"p": []}
                self.order = ["p"]
                return httpx.Response(200, json={"id": "pres-1"})
            self.saved.append(request.read())
            return httpx.Response(200, json={"id": "report-1"})
        if path == "/drive/v3/files" and request.method == "GET":
            return httpx.Response(200, json={"files": []})
        if path == "/drive/v3/files" and request.method == "POST":
            return httpx.Response(200, json={"id": "folder-1"})
        if path.startswith("/drive/v3/files/") and request.method == "GET":
            return httpx.Response(200, json={"parents": ["root"]})
        if path.startswith("/drive/v3/files/") and request.method == "PATCH":
            assert request.url.params["addParents"] == "folder-1"
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1]})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    def storage(self, request: httpx.Request) -> httpx.Response:
        if "signBlob" in request.url.path:
            return httpx.Response(200, json={"signedBlob": base64.b64encode(b"\x01\x02").decode()})
        if request.method == "POST":
            self.uploads += 1
            if self.store_fails(self.uploads):
                return httpx.Response(503, json={})
            name = request.url.params["name"]
            assert request.url.params["ifGenerationMatch"] == "0"
            assert name.startswith("publisher/") and re.fullmatch(
                r"publisher/[0-9a-f]{32}\.\w+", name
            )
            self.stored.add(name)
            self.ever_stored.add(name)
            return httpx.Response(200, json={"name": name})
        if request.method == "DELETE":
            self.stored.discard(unquote(request.url.path.rsplit("/o/", 1)[1]))
            return httpx.Response(204)
        raise AssertionError(request.url)

    def slides_api(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/v1/presentations":
            raise AssertionError("the Slides API ignores a page size: import a deck instead")
        if request.method == "POST" and path.endswith(":batchUpdate"):
            return self.batch(json.loads(request.content)["requests"])
        if request.method == "GET" and "/pages/" in path:
            slide = path.rsplit("/", 1)[-1]
            if slide not in self.slides:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"objectId": slide, "pageElements": self.tree(slide)})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "pageSize": self.page_size,
                    "slides": [{"objectId": s, "pageElements": self.tree(s)} for s in self.order],
                },
            )
        raise AssertionError(request.url)

    def tree(self, slide: str) -> list[dict]:
        def node(object_id):
            element = self.objects[object_id]
            result = {"objectId": object_id}
            if element.get("children"):
                result["elementGroup"] = {"children": [node(c) for c in element["children"]]}
            if "text" in element:
                result["shape"] = {
                    "text": {"textElements": [{"textRun": {"content": element["text"]}}]}
                }
            return result

        return [node(o) for o in self.slides[slide]]

    def batch(self, requests: list[dict]) -> httpx.Response:
        self.batches += 1
        # Atomic, as Slides is: check everything before changing anything.
        lengths = {k: len(v.get("text", "")) for k, v in self.objects.items()}
        for index, request in enumerate(requests):
            kind, body = next(iter(request.items()))
            if kind == "insertText" and "cellLocation" not in body:
                kept = "".join(ch for ch in body["text"] if ch >= " " or ch in "\t\n\u000b")
                lengths[body["objectId"]] = lengths.get(body["objectId"], 0) + len(kept)
            if kind == "updateTextStyle" and "cellLocation" not in body:
                end = body["textRange"]["endIndex"]
                have = lengths.get(body["objectId"], 0)
                if not have or end > have:
                    return httpx.Response(
                        400,
                        json={
                            "error": {
                                "message": f"Invalid requests[{index}].updateTextStyle: The end "
                                f"index ({end}) should not be greater than the existing text "
                                f"length ({have})."
                            }
                        },
                    )
            image = request.get("createImage")
            if image:
                parts = urlsplit(image["url"])
                name = parts.path.split("/", 2)[2]
                if (
                    "X-Goog-Signature" not in parts.query
                    or name not in self.stored
                    or image["objectId"] in self.refuse
                ):
                    return httpx.Response(
                        400,
                        json={
                            "error": {
                                "message": f"Invalid requests[{index}].createImage: "
                                f"There was a problem retrieving the image {image['url']}"
                            }
                        },
                    )
        for request in requests:
            kind, body = next(iter(request.items()))
            if kind == "createSlide":
                self.slides[body["objectId"]] = []
                self.order.insert(body["insertionIndex"], body["objectId"])
            elif kind == "deleteObject":
                self.slides.pop(body["objectId"], None)
                self.order.remove(body["objectId"])
            elif kind in {"createShape", "createImage", "createLine", "createTable"}:
                page = body["elementProperties"]["pageObjectId"]
                self.objects[body["objectId"]] = {"page": page}
                self.slides[page].append(body["objectId"])
            elif kind == "insertText" and "cellLocation" not in body:
                element = self.objects[body["objectId"]]
                kept = "".join(ch for ch in body["text"] if ch >= " " or ch in "\t\n\u000b")
                element["text"] = element.get("text", "") + kept
            elif kind == "groupObjects":
                children = body["childrenObjectIds"]
                page = self.objects[children[0]]["page"]
                for child in children:
                    self.slides[page].remove(child)
                self.objects[body["groupObjectId"]] = {"page": page, "children": children}
                self.slides[page].append(body["groupObjectId"])
        if self.lose_reply:
            self.lose_reply = False
            raise httpx.ReadError("the reply was lost")
        return httpx.Response(200, json={"replies": []})


# ------------------------------------------------------------------ converting


def job(tmp_path, doc, prepared):
    result = tmp_path / "result"
    result.mkdir(exist_ok=True)
    planned = plan(doc, prepared, title="placeholder")
    (result / "plan.json").write_text(json.dumps(planned.as_dict(result)), encoding="utf-8")
    manifest = {
        "source": {"sha256": "ab" * 32},
        "document": doc,
        "assets": {"assets": []},
        "report": {},
    }
    return tmp_path, manifest


def booklet(tmp_path):
    (tmp_path / "result").mkdir()
    prepared = pictures(tmp_path / "result", logo=(100, 100), photo=(300, 200))
    doc = document(
        [
            text_box(
                "el_1",
                0,
                (10, 10, 300, 60),
                # Ends in Publisher's paragraph mark, as the reader leaves it.
                paragraph(run("Reading at home\r", font="SassoonPrimaryInfant")),
            ),
            image("el_2", 1, (300, 10, 100, 100), "logo"),
        ],
        [
            image("el_3", 0, (20, 20, 300, 200), "photo"),
            image("el_4", 1, (20, 300, 100, 100), "logo"),
        ],
    )
    return job(tmp_path, doc, prepared)


def convert(tmp_path, fake: FakeGoogle, root, manifest, settings=READY, monkeypatch=None):
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setattr(
        publisher_convert, "storage_client", lambda: httpx.AsyncClient(transport=transport)
    )
    monkeypatch.setattr(publisher_convert, "credentials", lambda client: Token(client))

    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            return await publisher_convert.convert(
                root,
                manifest,
                Google("user-token", client),
                original_name="RWI booklet",
                settings=settings,
            )

    return asyncio.run(go())


def test_a_publication_is_built_page_by_page_and_checked(tmp_path, monkeypatch):
    fake = FakeGoogle()
    root, manifest = booklet(tmp_path)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert report["status"] == "completed_with_warnings", report["warnings"]
    assert report["url"] == "https://docs.google.com/presentation/d/pres-1/edit"
    assert report["verification"] == "objects_page_size_and_text_checked"
    assert fake.presentations == 1
    # Made by importing an empty deck of the publication's own size.
    presentation = zipfile.ZipFile(io.BytesIO(fake.deck)).read("ppt/presentation.xml").decode()
    assert '<p:sldSz cx="5346000" cy="7560000"/>' in presentation
    assert fake.order == ["wmt_page_0001", "wmt_page_0002"]  # Google's own slide removed
    assert fake.slides["wmt_page_0001"] == ["wmt_el_1", "wmt_el_2"]  # paint order
    assert fake.objects["wmt_el_1"]["text"] == "Reading at home"
    codes = [w["code"] for w in report["warnings"]]
    assert "objects_missing" not in codes and "text_differs" not in codes
    assert "font-substituted" in codes  # Sassoon → Andika, reported
    assert report["conversion"]["statusCounts"]["NATIVE"] == 3


def test_pictures_are_stored_briefly_and_the_bucket_is_left_empty(tmp_path, monkeypatch):
    fake = FakeGoogle()
    root, manifest = booklet(tmp_path)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert len(fake.ever_stored) == 3  # the logo once per page it is on, the photo once
    assert fake.stored == set()
    # The bucket sees only the app's own account; Drive and Slides only the person's.
    assert fake.tokens["app"] == {"Bearer sa-token"}
    assert fake.tokens["user"] == {"Bearer user-token"}
    saved = b"".join(fake.saved) + json.dumps(report).encode()
    assert b"X-Goog-Signature" not in saved and b"storage.googleapis.com" not in saved


def test_a_picture_slides_will_not_take_leaves_a_marked_box_not_a_lost_page(tmp_path, monkeypatch):
    fake = FakeGoogle(refuse={"wmt_el_3"})
    root, manifest = booklet(tmp_path)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert fake.slides["wmt_page_0002"] == ["wmt_el_3", "wmt_el_4"]  # the page was still built
    assert "picture from the original" in fake.objects["wmt_el_3"]["text"]
    codes = [w["code"] for w in report["warnings"]]
    assert "pictures_refused" in codes and "objects_missing" not in codes
    assert fake.stored == set()
    assert "problem retrieving" not in json.dumps(report)  # Google's words, with the link, stay out


def test_a_changed_page_size_is_reported(tmp_path, monkeypatch):
    wide = {
        "width": {"magnitude": 9144000, "unit": "EMU"},
        "height": {"magnitude": 5143500, "unit": "EMU"},
    }
    fake = FakeGoogle(page_size=wide)
    root, manifest = booklet(tmp_path)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    (note,) = [w for w in report["warnings"] if w["code"] == "page_size_changed"]
    assert "720 × 405" in note["message"] and "421 × 595" in note["message"]


def test_a_lost_reply_is_not_sent_twice(tmp_path, monkeypatch):
    fake = FakeGoogle(lose_reply=True)
    root, manifest = booklet(tmp_path)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert report["status"].startswith("completed")
    assert fake.batches == 3  # setup (applied, reply lost, found by looking) + two pages
    assert fake.order == ["wmt_page_0001", "wmt_page_0002"]


def test_nothing_is_made_where_conversion_is_not_set_up(tmp_path, monkeypatch):
    fake = FakeGoogle()
    root, manifest = booklet(tmp_path)
    report = convert(tmp_path, fake, root, manifest, settings=Settings(), monkeypatch=monkeypatch)
    assert report["status"] == "failed"
    assert report["warnings"][-1]["code"] == "not_convertible"
    assert fake.presentations == 0 and not fake.tokens["user"]


def test_without_a_plan_the_file_is_refused_plainly(tmp_path, monkeypatch):
    fake = FakeGoogle()
    root, manifest = booklet(tmp_path)
    (root / "result" / "plan.json").unlink()
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert report["warnings"][-1]["code"] == "plan_unavailable"
    assert fake.presentations == 0


def test_a_plan_cannot_point_outside_its_job(tmp_path, monkeypatch):
    fake = FakeGoogle()
    root, manifest = booklet(tmp_path)
    planned = json.loads((root / "result" / "plan.json").read_text())
    planned["pictures"]["logo"]["path"] = "../../secret.png"
    (root / "result" / "plan.json").write_text(json.dumps(planned))
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert report["status"].startswith("failed") and fake.presentations == 0


def test_the_worker_plans_a_parsed_bundle(tmp_path):
    from PIL import Image

    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    Image.new("RGB", (40, 30), "red").save(bundle / "assets" / ("a" * 64 + ".png"))
    doc = document([image("el_1", 0, (10, 10, 40, 30), "asset_0001")])
    assets = {
        "assets": [
            {
                "id": "asset_0001",
                "filename": "assets/" + "a" * 64 + ".png",
                "mimeType": "image/png",
                "byteLength": 100,
                "pixelWidth": 40,
                "pixelHeight": 30,
            }
        ]
    }
    (bundle / "document.json").write_text(json.dumps(doc))
    (bundle / "assets.json").write_text(json.dumps(assets))
    data = render_path(tmp_path)
    assert json.loads((tmp_path / "plan.json").read_text()) == data
    assert data["pictures"]["asset_0001"]["path"] == "bundle/assets/" + "a" * 64 + ".png"
    from workspace_toolkit.publisher_slides import Plan

    assert check(Plan.from_dict(data, tmp_path)) == []


# ------------------------------------------------------------------ the blank deck


def test_the_blank_deck_is_a_valid_package_of_the_right_size():
    from defusedxml.ElementTree import fromstring
    from workspace_toolkit.publisher_deck import MAX_EMU, blank_deck

    package = zipfile.ZipFile(io.BytesIO(blank_deck(420.944882, 595.275591)))
    for name in package.namelist():
        fromstring(package.read(name))  # every part is well-formed XML
    assert '<p:sldSz cx="5346000" cy="7560000"/>' in package.read("ppt/presentation.xml").decode()
    huge = zipfile.ZipFile(io.BytesIO(blank_deck(99999, 99999)))
    assert f'cx="{MAX_EMU}"' in huge.read("ppt/presentation.xml").decode()  # PowerPoint's limit


def test_the_summary_keeps_notes_that_differ_only_in_their_numbers():
    from workspace_toolkit.publisher_convert import summarise
    from workspace_toolkit.publisher_slides import Plan

    def line(page, message):
        return {
            "pageIndex": page,
            "status": "SUBSTITUTED",
            "notes": [{"code": "text-made-smaller", "message": message}],
        }

    report = {
        "elements": [
            line(1, "Smaller (to 90%)."),
            line(2, "Smaller (to 95%)."),
            line(3, "Smaller (to 90%)."),
        ],
        "warnings": [],
    }
    notes = summarise(Plan({}, [], [], {}, [], report))
    assert sorted(n["message"] for n in notes) == [
        "Smaller (to 90%). (2 on page 2, 4)",
        "Smaller (to 95%). (1 on page 3)",
    ]


def test_the_readers_own_notes_stay_out_of_the_summary_people_read():
    from workspace_toolkit.publisher_convert import summarise
    from workspace_toolkit.publisher_slides import Plan

    notes = [
        {"code": "text-made-smaller", "message": "Text was made smaller."},
        {
            "code": "group-inferred",
            "message": "inferred from a layer that contains another layer",
            "source": "reader",
        },
    ]
    report = {"elements": [{"pageIndex": 0, "status": "NATIVE", "notes": notes}], "warnings": []}
    summary = summarise(Plan({}, [], [], {}, [], report))
    assert [n["code"] for n in summary] == ["text-made-smaller"]


# ------------------------------------------------------------------ when storage fails (#108)


def picture_pages(tmp_path, count: int):
    (tmp_path / "result").mkdir()
    prepared = pictures(tmp_path / "result", **{f"p{i}": (40, 40) for i in range(count)})
    pages = [
        [
            text_box(f"el_t{i}", 0, (10, 10, 200, 40), paragraph(run(f"Page {i + 1}"))),
            image(f"el_p{i}", 1, (10, 80, 100, 100), f"p{i}"),
        ]
        for i in range(count)
    ]
    return job(tmp_path, document(*pages), prepared)


def test_a_picture_that_cannot_be_stored_leaves_a_marked_box_and_later_pages(tmp_path, monkeypatch):
    fake = FakeGoogle(store_fails=lambda n: n == 2)  # page 2's picture
    root, manifest = picture_pages(tmp_path, 3)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert report["status"] == "completed_with_warnings"
    assert fake.order == ["wmt_page_0001", "wmt_page_0002", "wmt_page_0003"]
    assert fake.slides["wmt_page_0002"] == ["wmt_el_t1", "wmt_el_p1"]
    assert "picture from the original" in fake.objects["wmt_el_p1"]["text"]
    assert fake.slides["wmt_page_0003"] == ["wmt_el_t2", "wmt_el_p2"]  # built after it
    assert "text" not in fake.objects["wmt_el_p2"]  # a real picture
    (note,) = [w for w in report["warnings"] if w["code"] == "pictures_not_sent"]
    assert note["message"].startswith("1 picture(s)") and note["detail"] == "HTTP 503"
    codes = [w["code"] for w in report["warnings"]]
    assert "pages_failed" not in codes and "objects_missing" not in codes
    assert fake.saved  # the report was saved beside the conversion


def test_storage_that_keeps_failing_is_not_asked_for_every_picture(tmp_path, monkeypatch):
    fake = FakeGoogle(store_fails=lambda n: True)
    root, manifest = picture_pages(tmp_path, 6)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert fake.uploads == publisher_convert.STORAGE_GIVE_UP
    assert len(fake.order) == 6
    assert all(
        "picture from the original" in fake.objects[f"wmt_el_p{i}"]["text"] for i in range(6)
    )
    (note,) = [w for w in report["warnings"] if w["code"] == "pictures_not_sent"]
    assert note["message"].startswith("6 picture(s)")


def test_a_page_that_fails_another_way_does_not_stop_the_rest(tmp_path, monkeypatch):
    fake = FakeGoogle()
    root, manifest = picture_pages(tmp_path, 3)
    real = publisher_convert.undelivered
    calls = []

    def once(requests, urls):
        calls.append(1)
        if len(calls) == 1:
            raise ToolkitError("picture_delivery_failed", "It went wrong.", 502)
        return real(requests, urls)

    monkeypatch.setattr(publisher_convert, "undelivered", once)
    report = convert(tmp_path, fake, root, manifest, monkeypatch=monkeypatch)
    assert report["status"] == "completed_with_warnings"
    assert fake.slides["wmt_page_0001"] == []
    assert fake.slides["wmt_page_0003"] == ["wmt_el_t2", "wmt_el_p2"]
    (note,) = [w for w in report["warnings"] if w["code"] == "pages_failed"]
    assert note["message"] == "Page 1 could not be made in Google Slides, and is left blank."
    assert report["conversion"]["refusals"] == [{"page": 1, "error": "picture_delivery_failed"}]


@pytest.mark.parametrize("call", ["email", "token"])
def test_the_metadata_server_failing_is_a_plain_error(call):
    def handle(request):
        return httpx.Response(500, text="no")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            creds = storage.MetadataCredentials(client)
            return await getattr(creds, call)()

    with pytest.raises(ToolkitError) as caught:
        asyncio.run(go())
    assert caught.value.code == "picture_delivery_failed" and caught.value.detail == "HTTP 500"


def test_a_copy_is_given_up_quietly_when_the_token_cannot_be_had():
    class Broken(Credentials):
        async def _fetch(self):
            raise KeyError("access_token")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: None)) as client:
            return await Bucket("b", SIGNER, Broken(client), client).delete("publisher/x.png")

    assert asyncio.run(go()) is False
