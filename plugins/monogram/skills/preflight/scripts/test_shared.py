#!/usr/bin/env python3
"""Tests for shared.py and the ledger's team report. A bare repo in a temp folder stands in for the team's
profile repo on GitHub, with two reviewers' clones of it; touches no real repo, profile or GitHub.

Usage: python3 test_shared.py
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for k, v in {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com', 'GIT_COMMITTER_NAME': 't',
             'GIT_COMMITTER_EMAIL': 't@example.com', 'GIT_CONFIG_NOSYSTEM': '1'}.items():
    os.environ[k] = v
import shared  # noqa: E402

PROFILE = {'name': 'team', 'sharedResults': True, 'repos': {'app': {'github': 'team/app', 'folder': 'app'}}}


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def git(d, *args):
    return sh('git', '-C', d, '-c', 'commit.gpgsign=false', *args)


def run(by, branch, outcome='fixed'):
    return {'repo': 'app', 'github': 'team/app', 'branch': branch, 'pr': 7, 'reviewedAt': '2026-11-10T10:00:00+00:00',
            'stateFile': f'/Users/{by}/app/.git/preflight/{branch}.json', 'repoRoot': f'/Users/{by}/app',
            'skillVersion': '12', 'settled': {'prState': 'MERGED', 'at': '2026-11-10T12:00:00+00:00', 'others': []},
            'findings': {'fp1': {'claim': 'a guard is missing', 'severity': 'Major', 'status': 'open', 'outcome': outcome,
                                 'finders': ['Security'], 'sites': ['lib/a.ts:10']}}}


def main():
    T = tempfile.mkdtemp(prefix='shared-test-')
    remote = os.path.join(T, 'remote.git')
    sh('git', 'init', '-q', '--bare', '-b', 'main', remote)
    seed = os.path.join(T, 'seed')
    sh('git', 'clone', '-q', remote, seed)
    with open(os.path.join(seed, 'profile.json'), 'w') as f:
        json.dump(PROFILE, f)
    with open(os.path.join(seed, 'checks.md'), 'w') as f:
        f.write('# checks\n')
    git(seed, 'add', '-A'); git(seed, 'commit', '-q', '-m', 'profile'); git(seed, 'push', '-q', 'origin', 'main')

    def clone(who):
        d = os.path.join(T, who, 'profiles', 'team')
        sh('git', 'clone', '-q', remote, d)
        return d
    alice, bob = clone('alice'), clone('bob')
    solo = os.path.join(T, 'alice', 'profiles', 'solo')  # a profile that does not share
    os.makedirs(solo)
    with open(os.path.join(solo, 'profile.json'), 'w') as f:
        json.dump({'name': 'solo', 'repos': {'lib': {'github': 'solo/lib'}}}, f)
    with open(os.path.join(alice, 'checks.md'), 'a') as f:
        f.write('- a rule alice is still writing\n')
    remote_log = lambda: git(remote, 'log', '--format=%s', 'main').splitlines()

    os.environ['PREFLIGHT_PROFILES'] = os.path.join(T, 'alice', 'profiles')
    os.environ['PREFLIGHT_LOGIN'] = 'alice'
    led = {'runs': {'app:claude_fix-x': run('alice', 'claude/fix-x'), 'lib:main': {**run('alice', 'main'), 'github': 'solo/lib'}}}
    first = shared.publish(led)
    path = os.path.join(alice, 'results', 'alice', 'app', 'claude_fix-x.json')
    body = json.load(open(path)) if os.path.exists(path) else {}
    pushed_checks = git(remote, 'show', 'main:checks.md')
    again = shared.publish(led)
    checks = [
        ('a review of a profile repo is written, committed and pushed', first == {'team': {'written': 1, 'pushed': True}}),
        ('the file names its reviewer and leaves out local paths', body.get('by') == 'alice' and 'stateFile' not in body
         and 'repoRoot' not in body and body.get('findings', {}).get('fp1', {}).get('claim') == 'a guard is missing'),
        ('a repo outside every sharing profile is not written', not os.path.exists(os.path.join(alice, 'results', 'alice', 'lib'))
         and not os.path.exists(os.path.join(solo, 'results'))),
        ('the commit says whose results it holds', remote_log()[0] == 'Review results from alice'),
        ("a profile edit in progress is neither committed nor lost", 'still writing' not in pushed_checks
         and 'still writing' in open(os.path.join(alice, 'checks.md')).read()),
        ('nothing new, nothing written or pushed', again == {'team': {'written': 0, 'pushed': False}} and len(remote_log()) == 2),
    ]

    os.environ['PREFLIGHT_PROFILES'] = os.path.join(T, 'bob', 'profiles')
    os.environ['PREFLIGHT_LOGIN'] = 'bob'
    bob_out = shared.publish({'runs': {'app:feat_y': run('bob', 'feat/y', outcome='declined')}})
    checks.append(('a clone behind the remote pulls, then pushes', bob_out == {'team': {'written': 1, 'pushed': True}}
                   and remote_log()[0] == 'Review results from bob'))

    os.environ['PREFLIGHT_PROFILES'] = os.path.join(T, 'alice', 'profiles')
    p = next(x for x in shared.sharing() if x['name'] == 'team')
    team, warning = shared.team(p)
    checks.append(("the team view has everyone's runs after a pull", warning is None
                   and sorted(team['runs']) == ['alice/app/claude_fix-x', 'bob/app/feat_y']))

    app = os.path.join(T, 'checkout', 'app')
    sh('git', 'init', '-q', app); git(app, 'remote', 'add', 'origin', 'https://github.com/team/app.git')
    env = {**os.environ, 'PREFLIGHT_LEDGER': os.path.join(T, 'ledger.json')}
    def rep(*a):
        r = subprocess.run([sys.executable, os.path.join(HERE, 'ledger.py'), 'report', '--json', *a], cwd=app, env=env,
                           capture_output=True, text=True)
        return json.loads(r.stdout or '{}')
    tr, mine = rep(), rep('--mine')
    checks += [
        ("report in a sharing profile's repo covers everyone, by reviewer", tr.get('team', {}).get('profile') == 'team'
         and tr.get('reviews') == 2 and tr.get('byReviewer', {}).get('alice', {}).get('fixed') == 1
         and tr.get('byReviewer', {}).get('bob', {}).get('declined') == 1),
        ('--mine reports this machine alone', 'team' not in mine and mine.get('reviews') == 0),
    ]

    broken = os.path.join(T, 'carol', 'profiles', 'team')
    sh('git', 'clone', '-q', remote, broken); git(broken, 'remote', 'set-url', 'origin', os.path.join(T, 'gone.git'))
    os.environ['PREFLIGHT_PROFILES'] = os.path.join(T, 'carol', 'profiles')
    os.environ['PREFLIGHT_LOGIN'] = 'carol'
    try:
        out = shared.publish({'runs': {'app:z': run('carol', 'z')}})['team']
    except Exception as e:  # noqa: BLE001 - the point is that it must not raise
        out = {'raised': repr(e)}
    checks.append(('a push that fails is reported, and the commit waits', out.get('pushed') is False and 'error' in out
                   and git(broken, 'log', '--format=%s', '-1') == 'Review results from carol'))

    real_login = shared.login
    shared.login = lambda: (_ for _ in ()).throw(AssertionError('gh was called'))
    os.environ['PREFLIGHT_PROFILES'] = os.path.join(os.path.dirname(HERE), 'profiles')  # bundled: nothing shares
    try:
        quiet = shared.publish(led)
    except AssertionError:
        quiet = 'called gh'
    checks.append(('no sharing profile: no change and no gh call', quiet == {}))
    shared.login = lambda: None
    os.environ['PREFLIGHT_PROFILES'] = os.path.join(T, 'alice', 'profiles')
    checks.append(('no login: an error to act on, nothing written', 'gh auth login' in shared.publish(led)['team'].get('error', '')))
    shared.login = real_login

    failed = 0
    for name, ok in checks:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    shutil.rmtree(T, ignore_errors=True)
    print(f'\n{len(checks) - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
