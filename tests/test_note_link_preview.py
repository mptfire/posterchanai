"""A SHARED POST OR PERSON LINK (`poster.place/<nevent1|note1|npub1|nprofile1…>`) UNFURLS LIKE DITTO'S.

"see <screenshot>, our links do not embed like Ditto's do in Discord" (2026-10-30): ditto.pub/nevent1… showed a card
(site name, "verita84 on Ditto", the post's text, the author's picture) and poster.place/nevent1qqsyxxtumqn22glw85…
showed nothing -- the /{entity} route served the bare shell for every entity except an article. Runs the shipped
route against the REPORTED link, the shipped decoder, and the shipped template for what lands in <head>.
"""
import asyncio
import re

import pytest

from tests.test_article_link_preview import _request

REPORTED = "nevent1qqsyxxtumqn22glw85j9n3z57qzyrtcnh8kgk3g0kypgfzzsjnqckms0f95ef"
NPUB = "npub1fdtthaqujtjcd6yfy7kt0zpkadyl9vvypq00s5nztnmche74d0tqv6uwwr"


def test_the_reported_link_and_the_other_forms_decode():
    from app.services import note_share
    ref = note_share.decode(REPORTED)
    assert ref and ref["type"] == "note" and len(ref["id"]) == 64, ref
    assert note_share.decode(NPUB) == {"type": "profile", "pubkey": "4b56bbf41c92e586e88927acb78836eb49f2b184081ef852625cf78be7d56bd6"}
    assert note_share.decode(REPORTED[:-1] + ("q" if REPORTED[-1] != "q" else "p")) is None, "a bad checksum must not decode"
    assert note_share.decode("naddr1" + REPORTED[7:]) is None


@pytest.fixture
def page(monkeypatch):
    import app.main as m
    from app.routers import client
    from app.services import note_share, profile_share
    seen = {}

    async def shell(request, db, meta=None):
        seen["meta"] = meta
        return "SHELL"

    async def plain(request, *a, **k):
        seen["plain"] = True
        return "PLAIN"
    monkeypatch.setattr(client, "render_client_shell", shell)
    monkeypatch.setattr(client, "client_app", plain)
    return m, seen, note_share, profile_share


def test_a_post_gets_name_on_posterchan_its_text_and_the_authors_picture(page, monkeypatch):
    m, seen, note_share, _ = page

    async def card(port, ref):
        assert ref["id"] == note_share.decode(REPORTED)["id"]
        return {"author": "verita84", "avatar": "https://media.poster.place/a.png", "image": "", "pubkey": "ab" * 32,
                "text": "Going to make PBS, PosterChan's version of OBS for simplified live streaming"}
    monkeypatch.setattr(note_share, "note_card", card)
    assert asyncio.run(m.nostr_entity_page(REPORTED, _request("/" + REPORTED))) == "SHELL"
    meta = seen["meta"]
    assert meta["title"] == "verita84 on PosterChan" and meta["site"] == "PosterChan", meta
    assert meta["description"].startswith("Going to make PBS"), meta
    assert meta["image"] == "https://media.poster.place/a.png" and meta["card"] == "summary", "a text post: the avatar, small, like Ditto"
    assert meta["url"] == "https://poster.place/" + REPORTED


def test_a_post_with_a_picture_gets_the_big_card():
    from app.services import note_share
    ev = {"content": "look https://media.poster.place/x.jpg nice nostr:npub1abc", "tags": []}
    assert note_share._first_image(ev) == "https://media.poster.place/x.jpg"
    assert note_share._plain(ev["content"]) == "look nice"
    meta = note_share.note_meta({"author": "a", "avatar": "https://m/a.png", "image": "https://media.poster.place/x.jpg", "text": "look"}, "u")
    assert meta["image"].endswith("x.jpg") and meta["card"] == "summary_large_image"


def test_a_person_link_gets_their_profile_card(page, monkeypatch):
    m, seen, _, profile_share = page

    async def prof(port, pk):
        return {"name": "Verita84", "about": "builds PosterChan", "picture": "https://media.poster.place/a.png"}
    monkeypatch.setattr(profile_share, "profile_card", prof)
    assert asyncio.run(m.nostr_entity_page(NPUB, _request("/" + NPUB))) == "SHELL"
    meta = seen["meta"]
    assert meta["title"].startswith("Verita84") and meta["description"] == "builds PosterChan" and meta["card"] == "summary", meta


def test_a_post_this_node_cannot_read_is_served_as_before(page, monkeypatch):
    m, seen, note_share, _ = page

    async def none(port, ref):
        return None
    monkeypatch.setattr(note_share, "note_card", none)
    assert asyncio.run(m.nostr_entity_page(REPORTED, _request("/" + REPORTED))) == "PLAIN" and "meta" not in seen


def test_the_card_lands_in_the_shipped_head_with_the_site_name(monkeypatch):
    from app.routers import client as client_router
    from app.services import note_share
    monkeypatch.setattr(client_router, "_default_theme", lambda db: "cyberpunk")
    meta = note_share.note_meta({"author": 'Bob "<b>"', "avatar": "", "image": "", "text": "a & b"}, "https://poster.place/" + REPORTED,
                                fallback_image="https://poster.place/static/icon-512.png")
    resp = asyncio.run(client_router.render_client_shell(_request("/" + REPORTED), db=None, meta=meta))
    html = resp.body.decode() if hasattr(resp, "body") else str(resp)
    head = html[:html.index("</head>")]
    assert re.search(r'<meta property="og:site_name" content="PosterChan">', head), "Discord's top line is og:site_name"
    assert head.count('property="og:site_name"') == 1
    assert '<meta name="twitter:card" content="summary">' in head
    assert "<b>" not in head, "the author name was not escaped"


def _head(meta, monkeypatch):
    from app.routers import client as client_router
    monkeypatch.setattr(client_router, "_default_theme", lambda db: "cyberpunk")
    resp = asyncio.run(client_router.render_client_shell(_request("/" + REPORTED), db=None, meta=meta))
    html = resp.body.decode() if hasattr(resp, "body") else str(resp)
    return html[:html.index("</head>")]


def test_a_video_post_plays_in_discord(monkeypatch):
    """"image and link embeds work i am told on discord but not video" (2026-10-31): the preview carried og:image only,
    so a video post unfurled as a still. Discord plays og:video when it is a direct https mp4/webm WITH a size. Measured
    in the shipped <head>, from a real imeta tag (url, m, dim, and the poster frame in `image`)."""
    from app.services import note_share
    ev = {"content": "watch this https://blossom.poster.place/abc.mp4", "tags": [
        ["imeta", "url https://blossom.poster.place/abc.mp4", "m video/mp4", "dim 1080x1920",
         "image https://blossom.poster.place/abc.jpg"]]}
    card = {"author": "a", "avatar": "https://m/a.png", "image": note_share._first_image(ev), "text": "watch this",
            "video": note_share._first_video(ev)}
    head = _head(note_share.note_meta(card, "https://poster.place/" + REPORTED), monkeypatch)
    assert '<meta property="og:video" content="https://blossom.poster.place/abc.mp4">' in head
    assert '<meta property="og:video:secure_url" content="https://blossom.poster.place/abc.mp4">' in head
    assert '<meta property="og:video:type" content="video/mp4">' in head
    assert '<meta property="og:video:width" content="1080">' in head and '<meta property="og:video:height" content="1920">' in head
    assert '<meta property="og:type" content="video.other">' in head
    assert '<meta property="og:image" content="https://blossom.poster.place/abc.jpg">' in head, "the poster frame is the still"
    assert note_share._plain(ev["content"]) == "watch this", "the video link is not in the text line"


def test_a_bare_video_link_plays_too_and_a_stream_playlist_is_not_offered():
    from app.services import note_share
    v = note_share._first_video({"content": "clip https://nostr.build/v/x.webm?x=1", "tags": []})
    assert v["url"] == "https://nostr.build/v/x.webm?x=1" and v["type"] == "video/webm"
    meta = note_share.note_meta({"author": "a", "avatar": "https://m/a.png", "image": "", "text": "", "video": v}, "u")
    assert meta["video_width"] == 1280 and meta["video_height"] == 720, "Discord shows no player without a size"
    assert meta["image"] == "https://m/a.png"
    hls = {"content": "", "tags": [["imeta", "url https://x.example/live.m3u8", "m application/x-mpegURL"]]}
    assert note_share._first_video(hls) == {}, "no unfurler plays a playlist"
    assert note_share._first_video({"content": "", "tags": [["imeta", "url http://x.example/a.mp4", "m video/mp4"]]}) == {}, \
        "https only: Discord refuses a mixed-content player"


def test_a_picture_post_names_no_video(monkeypatch):
    from app.services import note_share
    card = {"author": "a", "avatar": "", "image": "https://media.poster.place/x.jpg", "text": "pic",
            "video": note_share._first_video({"content": "pic https://media.poster.place/x.jpg", "tags": []})}
    head = _head(note_share.note_meta(card, "u"), monkeypatch)
    assert "og:video" not in head and '<meta property="og:type" content="article">' in head


def test_a_video_url_cannot_break_out_of_the_tag(monkeypatch):
    from app.services import note_share
    v = note_share._first_video({"content": "", "tags": [["imeta", 'url https://x.example/a.mp4?"><script>', "m video/mp4"]]})
    head = _head(note_share.note_meta({"author": "a", "avatar": "", "image": "", "text": "", "video": v}, "u"), monkeypatch)
    assert "<script>" not in head.split('og:video"')[1][:200]
