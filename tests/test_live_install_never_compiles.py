"""A LIVE INSTALL COPIES THE IMAGE; IT NEVER BUILDS PACKAGES.

2026-10-31: the install gate on posterchan-live-20261031 sat compiling C++ until the VM ran out of memory. The shell step
ran `emerge -uDN app-misc/posterchanos-shell` against the freshly synced overlay -- a deep update with new USE, which
rebuilds from source anything the copied image differs on. It had only ever run when the overlay sync worked, so it
appeared once the missing /tmp was fixed. The step now refreshes the shell package alone.
"""
import re
from pathlib import Path

SH = (Path(__file__).resolve().parents[1] / "os/gentoo.sh").read_text(encoding="utf-8")


def test_the_live_install_never_deep_updates():
    shell_step = SH.split("Syncing the PosterChanOS overlay", 1)[1].split("\n\t\telse\n", 1)[0]
    emerges = re.findall(r"_in '([^']*emerge[^']*)'", shell_step)   # the commands it RUNS, not its comments
    assert emerges, "the shell step no longer installs the shell -- re-point this test"
    for cmd in emerges:
        if "--sync" in cmd:
            continue
        assert not re.search(r"\s-[a-zA-Z]*D", cmd) and "--deep" not in cmd, ("a deep update compiles on install", cmd)
        assert not re.search(r"\s-[a-zA-Z]*N", cmd) and "--newuse" not in cmd, ("--newuse rebuilds on install", cmd)
        assert "--nodeps" in cmd, ("the shell step pulls dependencies, which can mean building them", cmd)
