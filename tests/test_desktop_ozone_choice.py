"""WHICH DISPLAY BACKEND THE DESKTOP APP ASKS FOR ON LINUX.

"Fine on Cinnamon with XLibre for me. Not so much Wayland" (2026-10-31, the AppImage on Cinnamon's Wayland session --
Muffin/Mutter). main.js asked Chromium for `ozone-platform-hint=auto` on every Linux machine, which moves the app onto
native Wayland wherever a Wayland session runs -- unlike Electron's own default and every other Electron app, which use
X11 through XWayland there. It is needed in exactly two places: PosterChanOS's shell, and a Wayland session with no X
server to fall back to. The SHIPPED decision function is run under node.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _decide(env, shell):
    src = (ROOT / "desktop/main.js").read_text()
    fn = "function wantsWaylandHint(" + src.split("function wantsWaylandHint(", 1)[1].split("\n}\n", 1)[0] + "\n}"
    out = subprocess.run([NODE, "-e", fn + "\nconsole.log(JSON.stringify(wantsWaylandHint(%s,%s)))"
                          % (json.dumps(env), json.dumps(shell))], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not NODE, reason="node required")
@pytest.mark.parametrize("env,shell,want", [
    ({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, False, False),   # Cinnamon/GNOME/KDE Wayland: XWayland, like other apps
    ({"DISPLAY": ":0"}, False, False),                                   # plain X11 (i3, Cinnamon on XLibre)
    ({"WAYLAND_DISPLAY": "wayland-1"}, False, True),                     # Wayland with no X server: X11 would exit
    ({"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"}, True, True),     # PosterChanOS's shell
])
def test_wayland_only_where_it_is_needed(env, shell, want):
    assert _decide(env, shell) is want


def test_the_hint_goes_through_the_decision():
    src = (ROOT / "desktop/main.js").read_text()
    body = src.split("function wireOzonePlatform() {", 1)[1].split("\n}", 1)[0]
    assert "wantsWaylandHint(process.env, SHELL_MODE)" in body
    assert body.count("appendSwitch('ozone-platform-hint'") == 1
