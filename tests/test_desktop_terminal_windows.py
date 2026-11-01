"""THE DESKTOP APP'S LOCAL TERMINAL ON WINDOWS AND MACOS.

"any way to make our terminal app work on the windows app?" -> "that shell has exited" (2026-10-31). desktop/localterm.js
spawned /bin/bash through util-linux `script` and sized it with `stty -F` + /proc -- none of which exists on Windows,
and macOS's BSD `script` takes different arguments -- so every terminal there died at once. Those two now get a real
PTY from node-pty (ConPTY on Windows), whose N-API prebuilds load in any Electron without a rebuild; Linux keeps its
no-native-module path.

What can run here does: the shell each OS starts, the packaging rules that decide whether the binary is in the app at
all (and only the right one), the error a build without it gives, and the shared smoke script against a REAL Linux
PTY. The Windows/macOS half runs that same script on the CI runners (desktop.yml "Local terminal works on this OS").
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESK = ROOT / "desktop"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node required")


def _node(script):
    done = subprocess.run([NODE, "-e", script], cwd=DESK, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1500:]
    return done.stdout.strip()


def test_each_os_starts_its_own_shell():
    out = json.loads(_node(
        "const t=require('./localterm.js');console.log(JSON.stringify(["
        "t.nativeShell('win32',{SystemRoot:'D:\\\\Win'}),t.nativeShell('win32',{}),"
        "t.nativeShell('darwin',{SHELL:'/bin/bash'}),t.nativeShell('darwin',{})]))"))
    assert out[0]["file"] == "D:\\Win\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    assert out[1]["file"].startswith("C:\\Windows\\System32\\WindowsPowerShell")
    assert out[2] == {"file": "/bin/bash", "args": ["-l"]}
    assert out[3]["file"] == "/bin/zsh"


def test_linux_never_loads_node_pty():
    assert _node("console.log(require('./localterm.js').ptyModule('linux'))") == "null"


def test_a_build_without_node_pty_says_so_instead_of_starting_a_dead_shell():
    """The old code on Windows 'started' bash, which exited at once: a terminal that reads as working and is not."""
    out = _node(
        "Object.defineProperty(process,'platform',{value:'win32'});"
        "const Module=require('module');const real=Module._load;"
        "Module._load=function(r,...a){if(r==='node-pty')throw new Error('not installed');return real.call(this,r,...a)};"
        "const t=require('./localterm.js');"
        "try{t.start({});console.log('started')}catch(e){console.log('refused: '+e.message)}")
    assert out.startswith("refused: ") and "node-pty" in out, out


def test_the_package_ships_node_pty_where_it_is_used_and_only_there():
    pkg = json.loads((DESK / "package.json").read_text())
    assert pkg["optionalDependencies"]["node-pty"] == "1.1.0", "pinned exactly: the prebuild layout is version-specific"
    b = pkg["build"]
    # Native binaries and the ConPTY helper exe/dll must be real files, not entries inside app.asar.
    assert any("node-pty" in p for p in b["asarUnpack"])
    # electron-builder must not try to recompile it: the N-API prebuilds ARE the build.
    assert b["npmRebuild"] is False
    assert "!**/node_modules/node-pty/**" in b["linux"]["files"], "the Linux app never loads it"
    assert any("darwin-*" in f for f in b["win"]["files"]) and any("win32-*" in f for f in b["mac"]["files"])
    assert any(f.endswith("*.pdb") for f in b["files"]), "53 MB of debug symbols must not ship"
    lock = json.loads((DESK / "package-lock.json").read_text())
    assert lock["packages"]["node_modules/node-pty"]["version"] == "1.1.0"


def test_ci_runs_a_real_terminal_on_windows_and_mac():
    wf = (ROOT / ".github/workflows/desktop.yml").read_text()
    step = wf.split("- name: Local terminal works on this OS", 1)[1].split("\n      - ", 1)[0]
    assert "matrix.name != 'linux'" in step and "node scripts/terminal-smoke.js" in step
    # Before packaging: a failure stops the build rather than shipping a dead terminal.
    assert wf.index("Local terminal works on this OS") < wf.index("${{ matrix.script }}") if "${{ matrix.script }}" in wf \
        else True


@pytest.mark.skipif(not (shutil.which("script") and shutil.which("bash")), reason="util-linux script required")
def test_the_smoke_script_drives_a_real_terminal_here():
    done = subprocess.run([NODE, "scripts/terminal-smoke.js"], cwd=DESK, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout[-500:] + done.stderr[-2000:]
    assert "terminal OK on linux" in done.stdout


def test_mac_build_makes_the_node_pty_helper_executable_before_using_it():
    """node-pty 1.1.0 ships prebuilds/darwin-*/spawn-helper as 0644; without +x every macOS terminal fails with
    "posix_spawnp failed" (the 2026-10-31 desktop build). The chmod must run before the smoke test (and so before
    packaging copies the file into the app)."""
    wf = (ROOT / ".github/workflows/desktop.yml").read_text()
    i = wf.index("- name: node-pty's macOS spawn-helper is executable")
    step = wf[i:].split("\n      - ", 1)[0]
    assert "matrix.name == 'mac'" in step and "chmod 755 node_modules/node-pty/prebuilds/darwin-*/spawn-helper" in step
    assert i < wf.index("- name: Local terminal works on this OS")


def test_the_utf8_stream_check_drives_the_path_it_feeds():
    """That runtime feeds bytes into a stubbed child_process (the Linux `script` path). On Windows/macOS localterm
    starts node-pty instead, so the stub saw nothing and the check failed the desktop build there. It pins linux."""
    src = (ROOT / "tests/client/terminal_utf8_stream_runtime.mjs").read_text()
    assert "k==='platform'?'linux'" in src and "process:linux" in src
