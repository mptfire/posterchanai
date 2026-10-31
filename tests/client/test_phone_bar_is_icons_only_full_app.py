"""THE PHONE'S BOTTOM BAR IS ICONS ONLY, AND SHORTER FOR IT.

"i think the text labels below the mobile buttons are a waste of space" (2026-10-31). Measured in the shipped
client at phone width: no label is drawn under any icon, the bar is no taller than its budget of 56px (it was 62px
with the labels), every button still has a name a screen reader announces, and the feed's last post still clears
the bar.

Fail-first: on the old stylesheet each label is a visible 11px line and the bar measures 62px.
"""
import asyncio
from pathlib import Path

import pytest

from tests.client import test_desktop_offline_full_app as desktop

pytestmark = pytest.mark.skipif(not Path('/opt/google/chrome/chrome').exists(), reason='Chrome required')


@pytest.fixture(scope='module', autouse=True)
def bundled_assets():
    yield from desktop.bundle.__wrapped__()


MEASURE = r"""(()=>{const nav=document.querySelector('.mobilenav');const nr=nav.getBoundingClientRect();
  const items=[...nav.querySelectorAll('.nav-item')].map(b=>{const l=b.querySelector('b');const lr=l&&l.getBoundingClientRect();
    const name=(b.getAttribute('aria-label')||(l&&l.textContent)||'').trim();
    return {name, labelArea: lr ? lr.width*lr.height : 0, h:b.getBoundingClientRect().height};});
  const feed=document.querySelector('.feed');
  return {shown:getComputedStyle(nav).display!=='none', navH:nr.height, items,
          feedPad:parseFloat(getComputedStyle(feed).paddingBottom)};})()"""


@pytest.mark.parametrize('size', [(390, 800), (360, 640)])
def test_the_phone_bar_draws_no_labels_and_is_shorter(size):
    got = {}

    async def check(b):
        await b.call('Emulation.setDeviceMetricsOverride',
                     dict(width=size[0], height=size[1], deviceScaleFactor=2, mobile=True))
        await desktop.login(b)
        await b.js("try{ if(window.PCOS && PCOS.isOn()) PCOS.exit(); }catch(_){}")
        await b.js("__PC.switchView('home'); true")
        await asyncio.sleep(0.8)
        got.update(await b.js(MEASURE))

    asyncio.run(desktop.with_browser('online', '', check))
    assert got['shown'], got
    assert got['navH'] <= 56.5, ("the bar is taller than its icons-only budget", got)
    for it in got['items']:
        assert it['labelArea'] <= 1, ("a text label is still drawn under a bottom-bar icon", it)
        assert it['name'], ("a bottom-bar button has no name for a screen reader", it)
        assert it['h'] >= 44, ("a bottom-bar button is under the 44px touch minimum", it)
    assert got['feedPad'] >= got['navH'], ("the feed's last post would sit under the bar", got)
