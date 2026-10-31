#!/usr/bin/env python3
"""THE DEPLOY GATE, RUN ON GITHUB ACTIONS (.github/workflows/gate.yml) INSTEAD OF THIS MACHINE.

2026-10-31: "use github actions to do our testing so we can save machine resources locally" -- and "we need to keep it
local way as an option". sync.sh calls this with the commit it is about to deploy:

  1. push that exact commit to `ci/<sha>` on the `github` remote (the workflow runs on any ci/** push);
  2. wait for the Deploy gate run whose head_sha IS that commit (never "the latest run" -- a run for another commit
     proves nothing about this one);
  3. exit 0 only when every part concluded success; 1 when any part failed (its failing tests are printed);
     3 when the answer could not be had (no gh, GitHub unreachable, no run appeared, the wait ran out) -- sync.sh then
     runs the LOCAL gate, so GitHub being down can delay a deploy but never skip its tests.

The ci/<sha> branch is deleted afterwards either way.
"""
import json
import subprocess
import sys
import time

WORKFLOW = 'gate.yml'
APPEAR_S = 300          # a push that starts no run within 5 min is "could not ask"
TOTAL_S = 100 * 60      # the workflow's own parts time out at 75 min; this is the outer bound
POLL_S = 30


def sh(*cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError('%s: %s' % (' '.join(cmd[:3]), (r.stderr or r.stdout).strip()[-400:]))
    return r.stdout.strip()


def repo_slug():
    url = sh('git', 'remote', 'get-url', 'github')
    tail = url.split('github.com', 1)[1].lstrip(':/')
    return tail[:-4] if tail.endswith('.git') else tail


def runs_for(slug, sha):
    out = sh('gh', 'api', 'repos/%s/actions/workflows/%s/runs?head_sha=%s&per_page=5' % (slug, WORKFLOW, sha))
    return json.loads(out).get('workflow_runs') or []


def failed_tests(slug, run_id):
    """The failing test ids from the failed parts' logs -- what a person needs to act on, not the whole log."""
    try:
        log = subprocess.run(['gh', 'run', 'view', str(run_id), '-R', slug, '--log-failed'],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return []
    keep = []
    for line in log.splitlines():
        body = line.split('\t')[-1]
        if 'failing in the full suite' in body or body.strip().startswith('tests/') or 'FAILED tests/' in body:
            keep.append(body.strip()[:240])
    return keep[-40:]


def main():
    sha = sh('git', 'rev-parse', 'HEAD')
    branch = 'ci/' + sha[:12]
    try:
        slug = repo_slug()
        sh('gh', 'auth', 'status')
        sh('git', 'push', '-q', '--force', 'github', '%s:refs/heads/%s' % (sha, branch))
    except Exception as e:
        print('[ci-gate] could not hand the commit to GitHub: %s' % e)
        return 3
    print('[ci-gate] %s pushed to %s; waiting for the Deploy gate on that commit' % (sha[:12], branch))
    started, run = time.time(), None
    try:
        while time.time() - started < TOTAL_S:
            try:
                runs = runs_for(slug, sha)
            except Exception as e:
                print('[ci-gate] could not ask GitHub (%s); retrying' % str(e)[:120])
                runs = []
            run = runs[0] if runs else None
            if not run and time.time() - started > APPEAR_S:
                print('[ci-gate] no Deploy gate run appeared for %s within %ds' % (sha[:12], APPEAR_S))
                return 3
            if run and run.get('status') == 'completed':
                ok = run.get('conclusion') == 'success'
                print('[ci-gate] %s: %s (%d min) %s' % ('PASSED' if ok else 'FAILED', run.get('conclusion'),
                      round((time.time() - started) / 60), run.get('html_url', '')))
                if not ok:
                    for line in failed_tests(slug, run['id']):
                        print('[ci-gate]   ' + line)
                return 0 if ok else 1
            time.sleep(POLL_S)
        print('[ci-gate] the Deploy gate did not finish within %d min' % (TOTAL_S // 60))
        return 3
    finally:
        subprocess.run(['git', 'push', '-q', 'github', ':refs/heads/' + branch], capture_output=True)


if __name__ == '__main__':
    sys.exit(main())
