"""Link previews for shared POSTS and PEOPLE: `poster.place/<note1|nevent1|npub1|nprofile1…>`.

"our links do not embed like Ditto's do in Discord" (2026-10-30): a ditto.pub/nevent1… link unfurls into a card --
site name, "<name> on Ditto", the post's text and the author's picture -- while the same post at
poster.place/nevent1… unfurled into nothing, because the `/{entity}` route served the bare shell for every entity but
an article. Same shape as article_share / git_share / profile_share: the event (and its author's kind 0) is read off
THIS node's relay and becomes `og:*` in <head>. Best-effort and local only -- never a fetch from a relay hint in the
URL (a link anyone can mint must not make this server dial an address of their choosing). Anything that cannot be
read leaves the page exactly as before.
"""
from __future__ import annotations

import logging
import re
import time

from app.services.article_share import _polymod, _CHARSET

logger = logging.getLogger(__name__)

SITE = "PosterChan"
_CARD_TTL = 300.0
_cache: dict[str, tuple[float, dict | None]] = {}
_IMG = re.compile(r"https://[^\s<>\"']+?\.(?:png|jpe?g|gif|webp|avif)(?:\?[^\s<>\"']*)?", re.I)
_VID = re.compile(r"https://[^\s<>\"']+?\.(mp4|webm|mov)(?:\?[^\s<>\"']*)?", re.I)
_VID_TYPE = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/mp4"}
_SHOWN_KINDS = (1, 20, 21, 22, 1068, 1111, 30023)          # what a shared post link can usefully preview


def decode(entity: str) -> dict | None:
    """note1/nevent1/npub1/nprofile1 -> {'type', 'id'|'pubkey', 'author'?} (checksum verified), else None."""
    s = (entity or "").strip().lower()
    hrp = s.split("1", 1)[0] if "1" in s else ""
    if hrp not in ("note", "nevent", "npub", "nprofile") or len(s) > 2000:
        return None
    data = s[len(hrp) + 1:]
    try:
        vals = [_CHARSET.index(c) for c in data]
    except ValueError:
        return None
    if len(vals) < 7 or _polymod([ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + vals) != 1:
        return None
    acc = bits = 0
    out = bytearray()
    for v in vals[:-6]:
        acc = (acc << 5) | v
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if hrp in ("note", "npub"):
        if len(out) != 32:
            return None
        return {"type": "note", "id": out.hex()} if hrp == "note" else {"type": "profile", "pubkey": out.hex()}
    res: dict = {}
    i = 0
    while i + 2 <= len(out):
        t, ln = out[i], out[i + 1]
        val = bytes(out[i + 2:i + 2 + ln])
        if len(val) != ln:
            return None
        if t == 0 and ln == 32:
            res["id" if hrp == "nevent" else "pubkey"] = val.hex()
        elif t == 2 and ln == 32 and hrp == "nevent":
            res["author"] = val.hex()
        i += 2 + ln
    if hrp == "nevent":
        return {"type": "note", **res} if "id" in res else None
    return {"type": "profile", "pubkey": res["pubkey"]} if "pubkey" in res else None


def _plain(text: str, n: int = 300) -> str:
    """A post's text as one preview line: links to media and nostr: references dropped, whitespace folded."""
    s = _IMG.sub(" ", text or "")
    s = re.sub(r"https?://\S+\.(?:mp4|webm|mov|m3u8|mp3|ogg|wav)(?:\?\S*)?", " ", s, flags=re.I)
    s = re.sub(r"nostr:[a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def _first_image(ev: dict) -> str:
    for t in ev.get("tags") or []:
        if isinstance(t, list) and t and t[0] == "imeta":
            url = next((x[4:] for x in t[1:] if isinstance(x, str) and x.startswith("url ")), "")
            mime = next((x[2:] for x in t[1:] if isinstance(x, str) and x.startswith("m ")), "")
            if url.startswith("https://") and (mime.startswith("image/") or _IMG.fullmatch(url)):
                return url[:2048]
    m = _IMG.search(ev.get("content") or "")
    return m.group(0)[:2048] if m else ""


def _first_video(ev: dict) -> dict:
    """The post's first PLAYABLE video -- {url, type, width, height, poster} or {}.

    "image and link embeds work on discord but not video" (2026-10-31): a post's preview carried og:image only, so a
    video post unfurled as a still card with nothing to play. Discord (and Telegram, Slack, X) plays a video from
    og:video when it is a direct mp4/webm over https with a size. An imeta tag says it best (NIP-92: `m video/…`,
    `dim WxH`, and `image` = a poster frame); a bare link in the text is the fallback. HLS (.m3u8) is skipped -- no
    unfurler plays a playlist, and naming one would only replace the picture with a broken player."""
    for t in ev.get("tags") or []:
        if not (isinstance(t, list) and t and t[0] == "imeta"):
            continue
        f = {}
        for x in t[1:]:
            if isinstance(x, str) and " " in x:
                k, v = x.split(" ", 1)
                f.setdefault(k, v)
        url, mime = f.get("url", ""), f.get("m", "")
        m = _VID.fullmatch(url) if url else None
        if not url.startswith("https://") or not (mime.startswith("video/") or m) or "mpegurl" in mime.lower():
            continue
        w, h = 0, 0
        dm = re.fullmatch(r"(\d{1,5})x(\d{1,5})", f.get("dim", ""))
        if dm:
            w, h = int(dm.group(1)), int(dm.group(2))
        poster = f.get("image", "")
        return {"url": url[:2048], "type": mime if mime.startswith("video/") else _VID_TYPE[m.group(1).lower()],
                "width": w, "height": h, "poster": poster[:2048] if poster.startswith("https://") else ""}
    m = _VID.search(ev.get("content") or "")
    return {"url": m.group(0)[:2048], "type": _VID_TYPE[m.group(1).lower()], "width": 0, "height": 0, "poster": ""} if m else {}


async def note_card(port: int, ref: dict) -> dict | None:
    """The shareable facts about one post, read off this node's relay; None when it is not here."""
    key = ref.get("id") or ""
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    card = None
    try:
        from app.services import nostr_store
        from app.services.profile_share import profile_card
        # strict: a dead relay must RAISE, not read as "no such post" and be cached for five minutes.
        evs = await nostr_store._ws_query(port, [{"ids": [key], "limit": 1}], timeout=4.0, strict=True)
        ev = next((e for e in (evs or []) if e.get("id") == key and e.get("kind") in _SHOWN_KINDS), None)
        if ev:
            prof = {}
            try:
                prof = await profile_card(port, ev.get("pubkey") or "") or {}
            except Exception:
                prof = {}
            card = {"author": prof.get("name") or "", "avatar": prof.get("picture") or "",
                    "text": _plain(ev.get("content") or ""), "image": _first_image(ev), "pubkey": ev.get("pubkey") or "",
                    "video": _first_video(ev)}
    except Exception as e:
        logger.debug("[note-share] card read failed for %s: %s", key[:12], e)
        return None
    _cache[key] = (now + _CARD_TTL, card)
    if len(_cache) > 4000:
        _cache.clear()
    return card


def note_meta(card: dict, url: str, fallback_image: str = "") -> dict:
    """A post card -> the shell's `meta`: "<name> on PosterChan", the text, and the post's picture (a big card)
    or the author's (a small one, as Ditto's is)."""
    who = card.get("author") or ("npub…" + (card.get("pubkey") or "")[-6:] if card.get("pubkey") else "Someone")
    big = bool(card.get("image"))
    meta = {"title": ("%s on %s" % (who, SITE))[:120],
            "description": card.get("text") or ("A post on %s." % SITE),
            "url": url, "image": card.get("image") or card.get("avatar") or fallback_image or "",
            "type": "article", "site": SITE, "card": "summary_large_image" if big else "summary"}
    v = card.get("video") or {}
    if v.get("url"):
        # A video post: og:video plays inline. The size is REQUIRED by Discord to show a player at all; unknown is
        # 1280x720, which it letterboxes. The still is the poster frame, else the post's picture, else the avatar.
        meta.update({"type": "video.other", "card": "summary_large_image", "video": v["url"], "video_type": v.get("type") or "video/mp4",
                     "video_width": v.get("width") or 1280, "video_height": v.get("height") or 720,
                     "image": v.get("poster") or meta["image"]})
    return meta
