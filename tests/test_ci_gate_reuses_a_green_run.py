"""scripts/ci_gate.py: a commit GitHub has already passed is not pushed (and so not tested) a second time, and a commit
with no green run is pushed and waited for."""
import runpy
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "scripts/ci_gate.py"


def _load(monkeypatch, runs):
    g = runpy.run_path(str(GATE))
    calls = []

    def sh(*cmd, check=True):
        calls.append(cmd)
        if cmd[:2] == ("git", "rev-parse"):
            return "a" * 40
        if cmd[:3] == ("git", "remote", "get-url"):
            return "https://github.com/o/r.git"
        return ""
    g["main"].__globals__["sh"] = sh
    g["main"].__globals__["runs_for"] = lambda slug, sha: runs
    g["main"].__globals__["time"].sleep = lambda s: None
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)
    return g, calls


def test_a_commit_already_green_is_not_pushed_again(monkeypatch):
    g, calls = _load(monkeypatch, [{"status": "completed", "conclusion": "success", "html_url": "u"}])
    assert g["main"]() == 0
    assert not any(c[:2] == ("git", "push") for c in calls), calls


def test_a_new_commit_is_pushed_and_its_result_returned(monkeypatch):
    g, calls = _load(monkeypatch, [])
    g["main"].__globals__["runs_for"] = (lambda it: (lambda slug, sha: next(it)))(iter([[], [], [{"status": "completed", "conclusion": "failure", "id": 1}]]))
    g["main"].__globals__["failed_tests"] = lambda slug, rid: []
    assert g["main"]() == 1
    assert any(c[:2] == ("git", "push") for c in calls), calls
