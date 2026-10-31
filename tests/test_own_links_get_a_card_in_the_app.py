"""A LINK TO THIS INSTANCE'S OWN PAGES GETS A CARD INSIDE THE APP.

2026-10-31: "i pasted https://poster.place/@npub…/bitcoin-whitepaper-day in Concord and just shows a link" -- "all
posterchan links are supposed to be good when shared". /client/preview refuses private addresses (SSRF), and from inside
the network poster.place resolves to the router, 192.168.0.1: every link to our own posts, articles, profiles and repos
came back {} in every in-app card while Discord, outside, showed the full card. Own links are now rendered by the app
itself (ASGI) and read with the same parser; nothing about the SSRF guard changes for anybody else's host.
"""
import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

PAGE = ('<html><head><meta property="og:title" content="Bitcoin Whitepaper Day · Mandalorian">'
        '<meta property="og:description" content="18 years since Satoshi&#x27;s paper">'
        '<meta property="og:image" content="https://image.example/w.jpg">'
        '<meta property="og:site_name" content="PosterChan"></head><body></body></html>')


def _wire(monkeypatch):
    from app.routers import client
    from app.services.activitypub import config as ap_config
    import app.main as main
    fake = FastAPI()

    @fake.get("/@{name}/{slug}")
    def page(name: str, slug: str):
        return HTMLResponse(PAGE)

    monkeypatch.setattr(main, "app", fake)
    monkeypatch.setattr(ap_config, "base_url", lambda: "https://poster.place")

    async def private(host):              # what the router's split DNS makes it: 192.168.0.1
        return False
    monkeypatch.setattr(client, "_is_public_host_async", private)
    client._preview_cache.clear()
    return client


def test_an_own_article_link_gets_its_title_picture_and_summary(monkeypatch):
    client = _wire(monkeypatch)
    url = "https://poster.place/@npub18z533j9gxhnlkqukp75wnd5mjv5njqkaj07atslnrk2dp9rxsp0q6650l4/bitcoin-whitepaper-day"
    got = json.loads(asyncio.run(client.link_preview(url)).body)
    assert got.get("title") == "Bitcoin Whitepaper Day · Mandalorian", got
    assert got.get("image") == "https://image.example/w.jpg" and got.get("site") == "PosterChan", got
    assert got.get("description") == "18 years since Satoshi's paper", got


def test_someone_elses_private_host_is_still_refused(monkeypatch):
    client = _wire(monkeypatch)
    got = json.loads(asyncio.run(client.link_preview("https://intranet.example/@a/b")).body)
    assert got == {}, "the own-page path must not open the SSRF guard for any other host"
