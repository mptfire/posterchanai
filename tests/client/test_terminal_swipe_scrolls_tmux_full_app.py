"""A swipe in the phone Terminal reaches tmux as SCROLLING, not as arrow keys.

"terminal on mobile is not scrollable" (2026-10-31). The SHIPPED term.js + client.css at 390px, real touch events
(CDP), against the stubbed PTY of test_terminal_split_panes_full_app (it echoes what it is sent, so writing an escape
sequence into it puts the terminal in that mode, exactly as tmux's output does). What the shell RECEIVES is read off
the PTY's write log.

  tmux as it now starts (alternate screen + SGR mouse reporting, tests/test_ssh_tmux_session_scrolls.py measures
  that on the real tmux): a finger dragged DOWN sends wheel-UP reports (`ESC[<64;...M`) -- tmux scrolls back -- and no
  arrow key at all.
  tmux as it used to start (alternate screen, no mouse reporting): the same swipe could only send up-arrows, i.e.
  recall shell history. Kept as the mechanism the fix depends on, so a change on either side shows up here.
"""
import asyncio

from tests.client import test_terminal_split_panes_full_app as rig

needs_chrome = rig.needs_chrome
CUR = "(PCTerm._panes().find(p=>p.focused)||{}).sid.replace('local:','')"


async def _swipe_down(b):
    r = await b.js("(()=>{const s=document.querySelector('.tty-pane .xterm-screen').getBoundingClientRect();"
                   "return [s.left+s.width/2, s.top+s.height*0.3, s.top+s.height*0.75]})()")
    x, y0, y1 = r
    await b.call("Input.dispatchTouchEvent", dict(type="touchStart", touchPoints=[dict(x=x, y=y0)]))
    for i in range(1, 13):
        await b.call("Input.dispatchTouchEvent", dict(type="touchMove", touchPoints=[dict(x=x, y=y0 + (y1 - y0) * i / 12)]))
        await asyncio.sleep(.02)
    await b.call("Input.dispatchTouchEvent", dict(type="touchEnd", touchPoints=[]))
    await asyncio.sleep(.3)


async def _sent_after_swipe(b, modes):
    await b.until("!!document.querySelector('.tty-pane .xterm-screen')")
    cur = await b.js(CUR)
    await b.js("pcTerm.write(%r, %r)" % (cur, modes))            # the stub echoes it: the terminal enters the modes
    await asyncio.sleep(.3)
    await b.js("__log.writes[%r]=[]" % cur)
    await _swipe_down(b)
    return "".join(await b.js("__log.writes[%r]||[]" % cur))


@needs_chrome
def test_a_swipe_scrolls_tmux_with_mouse_reporting(tmp_path):
    out = {}

    async def body(b):
        out["sent"] = await _sent_after_swipe(b, "\x1b[?1049h\x1b[?1000h\x1b[?1006h")

    rig._run(tmp_path, 390, 800, True, body)
    sent = out["sent"]
    assert "\x1b[<64;" in sent, ("a downward swipe did not reach tmux as wheel-up", repr(sent))
    assert "\x1b[A" not in sent and "\x1bOA" not in sent, ("the swipe still sent arrow keys", repr(sent))


@needs_chrome
def test_without_mouse_reporting_a_swipe_can_only_send_arrows(tmp_path):
    out = {}

    async def body(b):
        out["sent"] = await _sent_after_swipe(b, "\x1b[?1049h")

    rig._run(tmp_path, 390, 800, True, body)
    assert "\x1b[A" in out["sent"] or "\x1bOA" in out["sent"], repr(out["sent"])
