"""PROFILE -> MESSAGE OPENS THE CONVERSATION, EVEN WHEN MESSAGES LIVES ON ANOTHER WORKSPACE.

"windows: i clicked message on a user profile, it switched me to the workspace where messages is open and nothing
happens" (2026-10-31). The shipped desktop: Messages is open on workspace 1, the person is on workspace 2 and presses
Message on someone's profile. They must land in Messages ON THAT PERSON'S CONVERSATION -- the composer for them on
screen -- not on the list, and not on whoever was open before. Three starting states: Messages on its list, Messages
left on its Communities tab, and Messages already showing a different conversation.
"""
import asyncio
from pathlib import Path

import pytest

from tests.client import test_desktop_offline_full_app as desktop
from tests.client.test_workspaces_full_app import _click, _open

CHROME = pytest.mark.skipif(not Path('/opt/google/chrome/chrome').exists(), reason='Chrome required')
PEER = 'ab' * 32
PEER_NPUB = 'npub14w46h2at4'   # how the thread header names PEER
OTHER = 'cd' * 32

STATE = r"""(()=>{const vis=w=>getComputedStyle(w).display!=='none';
  const wins=[...document.querySelectorAll('#os-root .osw')].filter(vis);
  const msg=wins.find(w=>/Messages/.test((w.querySelector('.osw-title')||{}).textContent||''));
  const th=msg&&msg.querySelector('#dm-thread');
  return {ws:PCOS.workspaces().current, view:__PC.view&&__PC.view(), visible:wins.map(w=>(w.querySelector('.osw-title')||{}).textContent),
    thread:th?th.innerText.slice(0,200):null, composer:!!(th&&th.querySelector('textarea,[contenteditable=true]')),
    active:!!(msg&&msg.querySelector('#dm-list.has-active'))};})()"""


@pytest.fixture(scope='module', autouse=True)
def bundled_assets():
    yield from desktop.bundle.__wrapped__()


@CHROME
@pytest.mark.parametrize('before', ['list', 'communities-tab', 'another-conversation'])
def test_message_on_a_profile_opens_that_conversation_across_workspaces(before):
    got = {}

    async def check(b):
        await b.call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
        await desktop.login(b)
        await b.until("document.body.classList.contains('os-on')")
        await b.js("try{localStorage.removeItem('pc_osWorkspaces')}catch(_){};true")
        await _open(b, 'messages', 'Messages')
        if before == 'communities-tab':
            await b.js("__PC.switchView('concord');true")
            await asyncio.sleep(1.0)
        elif before == 'another-conversation':
            await b.js("__PC.openDMWith(%r);true" % OTHER)
            await b.until("((document.querySelector('#dm-thread')||{}).innerText||'').includes('npub1ehxumnwd')")
        await b.js("PCOS.addWorkspace();true")
        await b.until("PCOS.workspaces().current===1")
        # Their profile, on THIS workspace, and its ☰ -> Message -- the clicks the person made.
        await b.js("__PC.openProfile(%r);true" % PEER)
        await b.until("!!document.querySelector('#prof-menu')")
        await asyncio.sleep(.5)
        got['before'] = await b.js(STATE)
        await _click(b, '#prof-menu')
        await b.until("[...document.querySelectorAll('.menu-pop [data-m]')].some(x=>/Message/.test(x.textContent))")
        await b.js("[...document.querySelectorAll('.menu-pop [data-m]')].find(x=>/Message/.test(x.textContent)).click();true")
        await b.until("PCOS.workspaces().current===0")
        for _ in range(40):
            got.clear(); got.update(await b.js(STATE))
            if got.get('composer') and PEER_NPUB in (got.get('thread') or ''):
                break
            await asyncio.sleep(.25)

    asyncio.run(desktop.with_browser('online', '', check))
    assert got.get('ws') == 0, got
    assert got.get('composer') and got.get('active'), ("Message switched workspace and did not open the conversation", got)
    assert PEER_NPUB in (got.get('thread') or ''), ("Messages opened, on somebody else's conversation", got)
