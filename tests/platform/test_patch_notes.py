"""The public "What's new" page, where staff check whether their problem was fixed."""

from __future__ import annotations

from starlette.testclient import TestClient
from workspace_toolkit import patch_notes
from workspace_toolkit.patch_notes import KINDS, RELEASES
from workspace_toolkit.web import create_app

from .test_web import configured


def anonymous():
    settings = configured()
    return TestClient(create_app(settings), base_url=settings.base_url)


def test_the_page_is_public_and_lists_what_changed():
    client = anonymous()
    response = client.get("/whats-new")

    assert response.status_code == 200
    assert "What&#8217;s new" in response.text
    assert "Rich Text Format files can now be converted" in response.text


def test_the_converter_page_links_to_it():
    client = anonymous()
    assert 'href="/whats-new"' in client.get("/").text


def test_releases_are_newest_first_and_each_change_has_a_known_kind():
    days = [day for day, _ in RELEASES]
    assert days == sorted(days, reverse=True), "newest release first"
    for _, changes in RELEASES:
        assert changes, "an empty release"
        for kind, applies, text in changes:
            assert kind in KINDS
            assert applies.strip() and text.strip()


def test_notes_name_no_client_or_ticket():
    page = patch_notes.render().lower()
    for word in ("ticket", "westcliffe", "newbald", "658", "0650"):
        assert word not in page


def test_text_is_escaped(monkeypatch):
    monkeypatch.setattr(
        patch_notes,
        "RELEASES",
        [(RELEASES[0][0], [("New", "<b>Word</b>", "<script>alert(1)</script>")])],
    )
    page = patch_notes.render()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<b>Word</b>" not in page
