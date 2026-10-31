"""SWITCHING CHANNELS IN A COMMUNITY IS QUICK.

Vyram, eaeb13f1 (2026-10-29): "Channel switching still has a delay but it's shorter then it was before." The shipped
client at phone size with the CPU slowed 4x (a mid-range phone): a local community with two busy channels (260
messages each); a channel button is pressed and the time until the other channel's messages are on screen is
measured, over several switches.

A switch rebuilds every message of the room. Skipping off-screen rows (content-visibility) measured 556 -> 377 ms but
blanked the pane while scrolling -- the "Smoother Community Scrolling" bug -- so it was NOT shipped. This is a guard
on the switch time at phone speed; the numbers are printed for the record.
"""
import asyncio
import json
from pathlib import Path

import pytest

from tests.client import test_desktop_offline_full_app as desktop
from tests.client.test_concord_live_messages_keep_the_scroller_full_app import NO_OS

CHROME = pytest.mark.skipif(not Path('/opt/google/chrome/chrome').exists(), reason='Chrome required')


@pytest.fixture(scope='module', autouse=True)
def bundled_assets():
    yield from desktop.bundle.__wrapped__()


ROOM = r'''(()=>{const pk=__PC.me().pubkey,ID='switch-room';
localStorage.setItem('pc.concord.rooms.v1.'+pk,JSON.stringify([{name:'Switch',naddr:ID,local:true,channels:[{name:'general',private:false},{name:'random',private:false}]}]));
localStorage.setItem('pc.concord.active.v1.'+pk,'0');
const words='the relay answered and the room kept every message we sent over the long weekend while somebody fixed the build again'.split(' ');
const mk=(tag)=>{const msgs=[],t0=Date.now()-300*60000;for(let i=0;i<260;i++){const n=8+(i*7)%40,s=[];for(let j=0;j<n;j++)s.push(words[(i*3+j)%words.length]);
  msgs.push({id:tag+i,by:'Member '+(i%9),pubkey:String(i%9).repeat(64),at:t0+i*60000,text:tag+' #'+i+' '+s.join(' ')});}return msgs;};
localStorage.setItem('pc.concord.test.'+ID,JSON.stringify(mk('g')));
localStorage.setItem('pc.concord.test.'+ID+'.random',JSON.stringify(mk('r')));
__PC.switchView('concord');return true;})()'''

VISIBLE_ROWS = """(()=>{const b=[...document.querySelectorAll('.cc-messages')].find(x=>{const r=x.getBoundingClientRect();return r.width>1&&r.height>1;});
  return b?[...b.querySelectorAll('.cc-message')].filter(m=>{const r=m.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight;}).map(m=>m.textContent):[];})()"""

SWITCH = """(async name => {
  const b = document.querySelector('[data-cc-channel="' + name + '"]');
  const want = name === 'random' ? 'r #' : 'g #';
  const t0 = performance.now(); b.click();
  const sync = performance.now() - t0;
  const shown = () => { const box=[...document.querySelectorAll('.cc-messages')].find(x=>{const r=x.getBoundingClientRect();return r.width>1&&r.height>1;});
    return !!box && [...box.querySelectorAll('.cc-message')].some(m=>m.textContent.includes(want)); };
  while (!shown() && performance.now() - t0 < 10000) await new Promise(r => setTimeout(r, 4));
  await new Promise(r => requestAnimationFrame(() => setTimeout(r, 0)));
  return { sync: Math.round(sync), painted: Math.round(performance.now() - t0) };
})"""


@CHROME
def test_switching_channels_shows_the_other_channel_quickly():
    got = {}

    async def check(b):
        await b.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 800, 'deviceScaleFactor': 2, 'mobile': True})
        await desktop.login(b)
        await b.js(NO_OS + 'true')
        await b.js(ROOM)
        await b.until("!!document.querySelector('[data-cc-channel=\"random\"]')")
        await b.js("document.querySelector('[data-cc-channel=\"general\"]').click();true")
        await b.until("%s.some(t=>t.includes('g #'))" % VISIBLE_ROWS)
        await b.call('Emulation.setCPUThrottlingRate', {'rate': 4})
        runs = []
        for name in ('random', 'general', 'random', 'general', 'random', 'general'):
            # Back on the channel list (a phone shows one or the other), then press the channel.
            await b.js("(()=>{const x=document.querySelector('#cc-back-channels');if(x&&getComputedStyle(x).display!=='none'&&x.offsetParent)x.click();return true})()")
            await asyncio.sleep(.3)
            runs.append(await b.js("(%s)(%s)" % (SWITCH, json.dumps(name))))
        await b.call('Emulation.setCPUThrottlingRate', {'rate': 1})
        got['runs'] = runs
        assert not await b.js("__errors.slice()")

    asyncio.run(desktop.with_browser('online', '?pcShell=1', check))
    print('switch', got)
    times = sorted(r['painted'] for r in got['runs'])
    assert times[len(times) // 2] < 900, ("switching channels takes too long on a phone", got)
