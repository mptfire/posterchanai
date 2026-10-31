"""A terminal's tmux session turns mouse reporting ON, for that session only.

"terminal on mobile is not scrollable" (2026-10-31). Every remote terminal runs inside `tmux new-session -A`, and tmux
draws on the terminal's ALTERNATE screen, which has no scrollback -- the history is tmux's. With tmux's default
`mouse off`, xterm can hand a swipe or a wheel to it only as up/down arrow keys, which walk the shell's command history.
With `mouse on` the wheel reaches tmux and tmux scrolls.

The SHIPPED `_mux_command`, run under bash in a real pty against the real tmux (its own socket directory), measures what
the terminal is told: the alternate screen AND mouse reporting (SGR) are switched on, on a fresh session and again on a
reattach; and the option is the session's, never the server's global one -- that tmux server is shared with whatever the
host's owner runs in it.

Fail-first: the old command enters the alternate screen with no mouse reporting.
"""
import os
import pty
import select
import shutil
import subprocess
import time

import pytest

from app.services import ssh_service

pytestmark = pytest.mark.skipif(not (shutil.which("tmux") and shutil.which("bash")), reason="tmux required")


def _env(tmp_path):
    env = dict(os.environ, TERM="xterm-256color", TMUX_TMPDIR=str(tmp_path), HOME=str(tmp_path), SHELL="/bin/sh")
    env.pop("TMUX", None)
    return env


def _attach(env, name, seconds=2.5):
    """Run the session command in a pty; return what it wrote to the terminal, then detach (the session lives on)."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("bash", ["bash", "-c", ssh_service._mux_command(name)], env)
    out, t = b"", time.time()
    while time.time() - t < seconds:
        r, _, _ = select.select([fd], [], [], .1)
        if r:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
    subprocess.run(["tmux", "detach-client", "-s", name], env=env, capture_output=True)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    os.close(fd)
    return out


def _show(env, *args):
    return subprocess.run(["tmux", "show-options", *args], env=env, capture_output=True, text=True).stdout


def test_the_session_reports_the_mouse_so_a_swipe_scrolls(tmp_path):
    env = _env(tmp_path)
    try:
        first = _attach(env, "pcai-7-a")
        assert b"\x1b[?1049h" in first, "tmux no longer uses the alternate screen -- re-read this test"
        assert b"\x1b[?1000h" in first and b"\x1b[?1006h" in first, (
            "a fresh session does not turn mouse reporting on: a swipe reaches tmux as arrow keys", first[-400:])
        again = _attach(env, "pcai-7-a")
        assert b"\x1b[?1000h" in again, "a REATTACHED session does not report the mouse"
        assert "mouse on" in _show(env, "-t", "pcai-7-a", "mouse")
        assert "mouse on" not in _show(env, "-g", "mouse"), "mouse was set for the whole tmux server, not this session"
    finally:
        subprocess.run(["tmux", "kill-server"], env=env, capture_output=True)
