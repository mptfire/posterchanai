"""Bookmark sync on PosterFox for Android, where Firefox has no bookmarks API.

"it only makes sense to do posterfox on android if bookmarks work" (2026-10-31). Firefox for Android implements no
`bookmarks` WebExtension API (MDN browser-compat-data: every method version_added:false), so the PosterChan extension
could not sync bookmarks there. PosterFox for Android ships the extension BUILT IN and answers the API itself from the
app's bookmark storage over native messaging; extension/bookmarks-native.js is the extension's half. The sync engine is
the desktop's bookmarks.js, unchanged.

`android_bookmarks_sim.js` runs the shipped bookmarks-native.js + bookmarks.js against a fake app that speaks exactly
the protocol the Kotlin bridge implements, next to a desktop Firefox on one relay:

  desktop -> phone        a toolbar folder lands on the phone's toolbar, in its folder
  phone -> desktop        a bookmark made in the app's own UI reaches the desktop through the derived event (no merge)
  deletes                 cross both ways, and nothing else goes
  outage                  a tree the app could not read deletes nothing anywhere, measured during the outage
  first sync              a union: both sides gain, neither loses
  quiet                   a settled pair writes nothing more
  late app                the app starts listening after the extension's first read: GeckoView holds the connection
                          and drops what was posted on it, so the stand-in sends nothing until the app's hello

Each was shown to fail against a broken stand-in (no events fired; a failed read taken as an empty tree).

The build half: only the Android variant of the extension asks for `nativeMessaging` and loads the stand-in -- a new
permission in the store builds would put a prompt in front of every desktop user.
"""
import json
import os
import shutil
import subprocess

import pytest

from tests.client.simulation_results import require_successful_scenarios

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SIM = os.path.join(HERE, "android_bookmarks_sim.js")
EXT = os.path.join(ROOT, "extension")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture(scope="module")
def results():
    r = subprocess.run(["node", SIM], capture_output=True, text=True, timeout=300)
    assert r.stdout.strip(), f"the simulation produced nothing:\n{r.stderr[-2000:]}"
    try:
        rows = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"simulation crashed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return require_successful_scenarios(rows, r)


@pytest.mark.parametrize("name", [
    "Android gets a bookmarks API from the app; a browser with its own keeps it",
    "desktop bookmarks reach the phone in the right container and folder",
    "a bookmark made on the phone reaches the desktop",
    "deletes cross both ways and nothing else goes",
    "a failed read deletes nothing anywhere",
    "first sync gains both sides and deletes none",
    "a settled phone and desktop stop writing",
    "a phone whose app starts listening late still syncs both ways",
])
def test_scenario(results, name):
    assert name in results, f"scenario missing: {name!r} (have {list(results)})"


@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 required by build.sh")
def test_only_the_android_build_asks_for_native_messaging(tmp_path):
    work = tmp_path / "ext"
    shutil.copytree(EXT, work / "extension", ignore=shutil.ignore_patterns("dist"))
    for rel in ("static/js/client/vaultcore.js", "static/vendor/nostr/nostr.bundle.js"):
        os.makedirs(work / os.path.dirname(rel), exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), work / rel)
    r = subprocess.run(["bash", "build.sh"], cwd=work / "extension", capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    dist = work / "extension" / "dist"
    android = json.loads((dist / "android" / "manifest.json").read_text())
    scripts = android["background"]["scripts"]
    assert "nativeMessaging" in android["permissions"]
    assert scripts.index("bookmarks-native.js") < scripts.index("bookmarks.js") < scripts.index("background.js")
    assert (dist / "android" / "bookmarks-native.js").is_file() and (dist / "posterchan-passwords-android.zip").is_file()
    for store in (json.loads((work / "extension" / "manifest.json").read_text()),
                  json.loads((dist / "chrome" / "manifest.json").read_text())):
        assert "nativeMessaging" not in store["permissions"], "a store build asks every desktop user for a new permission"
        assert "bookmarks-native.js" not in json.dumps(store)
