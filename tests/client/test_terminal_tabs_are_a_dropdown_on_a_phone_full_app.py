"""On a phone the Terminal's tabs are a dropdown; on a wider screen they stay tabs.

"terminal tabs are terrible on mobile and probably should be a dropdown on mobile only. tabs dont fit" (2026-10-31).
The SHIPPED term.js + client.css against the desktop's local PTY stubbed as preload injects it
(test_terminal_split_panes_full_app's rig), with two shells running:

  phone (390px)   no tab is drawn; one dropdown inside the bar lists both shells and names the current one;
                  choosing the other shell in it switches the terminal to that shell; the × beside it closes
                  the current shell; nothing scrolls the page sideways. A− / A+ move into ⋯ ("Larger text" /
                  "Smaller text") so the dropdown has room, and they still change the text size.
  desktop         the tabs and A− / A+ are drawn; the dropdown and the ⋯ copies are not.

Fail-first: on the old code the phone draws both tabs (the strip scrolls sideways) and there is no dropdown.
"""
import asyncio

from tests.client import test_terminal_split_panes_full_app as rig

needs_chrome = rig.needs_chrome

STATE = r"""(()=>{const vis=e=>!!e&&getComputedStyle(e).display!=='none'&&e.getBoundingClientRect().width>0;
  const bar=document.querySelector('.tty-bar').getBoundingClientRect(), sel=document.getElementById('tty-tab-select');
  const sr=sel&&sel.getBoundingClientRect();
  return {tabs:[...document.querySelectorAll('#tty-sessions .tty-sess')].filter(vis).length,
    pick:vis(sel), inBar:!!sr&&sr.top>=bar.top-0.5&&sr.bottom<=bar.bottom+0.5&&sr.right<=innerWidth+0.5,
    options:sel?[...sel.options].map(o=>o.value).filter(Boolean):[], value:sel?sel.value:null,
    kill:vis(document.querySelector('.tty-pick-kill')), barFont:vis(document.getElementById('tty-font-more')),
    pickW:sr?Math.round(sr.width):0, font:+(localStorage.getItem('pc_tty_font_size')||0),
    cur:(PCTerm._panes().find(p=>p.focused)||{}).sid||'', hScroll:document.documentElement.scrollWidth>innerWidth+1};})()"""


async def _two_shells(b):
    await b.until("document.querySelectorAll('#tty-sessions [data-tab]').length>=2")
    await asyncio.sleep(.3)
    return await b.js(STATE)


@needs_chrome
def test_phone_tabs_are_a_dropdown(tmp_path):
    out = {}

    async def body(b):
        out["start"] = await _two_shells(b)
        other = next(v for v in out["start"]["options"] if v != out["start"]["cur"])
        await b.js("(v=>{const s=document.getElementById('tty-tab-select');s.value=v;s.dispatchEvent(new Event('change',{bubbles:true}));})(%r)" % other)
        await b.until("(PCTerm._panes().find(p=>p.focused)||{}).sid===%r" % other)
        await asyncio.sleep(.3)
        out["switched"] = await b.js(STATE)
        await b.shot("phone-terminal-dropdown")
        await b.click_sel(".tty-pick-kill")
        await b.until("!document.querySelector('#tty-sessions [data-tab=\"%s\"]')" % other)
        await asyncio.sleep(.3)
        out["closed"] = await b.js(STATE)
        await b.click_sel("#tty-more")
        out["menuFont"] = await b.js("getComputedStyle(document.getElementById('tty-more-font-more')).display!=='none'")
        before = (await b.js(STATE))["font"]
        await b.click_sel("#tty-more-font-more")
        await asyncio.sleep(.3)
        out["fontGrew"] = (await b.js(STATE))["font"] > before if before else (await b.js(STATE))["font"] > 0
        grown = (await b.js(STATE))["font"]
        await b.click_sel("#tty-more")
        await b.click_sel("#tty-more-font-less")
        await asyncio.sleep(.3)
        out["fontShrank"] = (await b.js(STATE))["font"] < grown

    rig._run(tmp_path, 390, 800, True, body)
    s = out["start"]
    assert s["tabs"] == 0, ("tabs are still drawn on a phone", s)
    assert s["pick"] and s["inBar"], ("no terminal dropdown inside the bar", s)
    assert len(s["options"]) == 2 and s["value"] == s["cur"], ("the dropdown does not list the shells / name the current one", s)
    assert s["kill"] and not s["hScroll"], s
    assert not s["barFont"] and s["pickW"] >= 120, ("the dropdown is squeezed by A−/A+ in the bar", s)
    assert out["menuFont"] and out["fontGrew"], ("⋯ -> Larger text is missing or does nothing on a phone", out)
    assert out["fontShrank"], ("⋯ -> Smaller text does nothing on a phone", out)
    w = out["switched"]
    assert w["cur"] != s["cur"] and w["value"] == w["cur"], ("choosing a shell in the dropdown did not switch to it", w)
    c = out["closed"]
    assert len(c["options"]) == 1 and w["cur"] not in c["options"], ("the × did not close the current shell", c)


@needs_chrome
def test_desktop_keeps_its_tabs(tmp_path):
    out = {}

    async def body(b):
        out.update(await _two_shells(b))
        await b.click_sel("#tty-more")
        out["menuFont"] = await b.js("getComputedStyle(document.getElementById('tty-more-font-more')).display!=='none'")

    rig._run(tmp_path, 1280, 800, False, body)
    assert out["tabs"] == 2 and not out["pick"] and not out["kill"], ("the desktop terminal lost its tabs", out)
    assert out["barFont"] and not out["menuFont"], ("A−/A+ moved on the desktop too", out)
