#!/usr/bin/env python3
"""Tests for ledger.py. Builds fake repos and fake PR threads in a temp folder; touches no real repo or GitHub.

Usage: python3 test_ledger.py [path/to/ledger.py]
"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ['PREFLIGHT_PROFILES'] = os.path.join(os.path.dirname(HERE), 'profiles')  # bundled only
LEDGER_PY = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, 'ledger.py')


def fake_repo(root, folder, states):
    path = os.path.join(root, folder)
    os.makedirs(path)
    subprocess.run(['git', 'init', '-q', path], check=True)
    sdir = os.path.join(path, '.git', 'subcore-review')
    os.makedirs(sdir)
    for name, data in states.items():
        with open(os.path.join(sdir, name), 'w') as f:
            json.dump(data, f)


def thread(fp, path, line, comments, resolved=False, outdated=False, fixed=False):
    return {'id': f'T-{path}-{line}', 'ours': fp is not None, 'fingerprint': fp, 'path': path, 'line': line,
            'isResolved': resolved, 'isOutdated': outdated, 'fixedMark': fixed,
            'comments': [{'author': a, 'body': b} for a, b in comments]}


def main():
    T = tempfile.mkdtemp(prefix='ledger-test-')
    os.environ['PREFLIGHT_REPOS'] = os.pathsep.join(os.path.join(T, d) for d in ('web', 'api-server'))
    os.environ['PREFLIGHT_LEDGER'] = os.path.join(T, 'ledger.json')
    fake_repo(T, 'web', {'claude_offer-check.json': {
        'lastReviewed': 'abc', 'reviewedAt': '2026-10-24T10:00:00+00:00', 'skillVersion': '8', 'mode': 'full',
        'findings': [
            {'id': 'F1', 'fingerprint': 'fp-fixed', 'claim': 'voice kept', 'severity': 'Minor', 'finders': ['Contracts', 'Claims'],
             'sites': ['lib/a.ts:40'], 'status': 'open'},
            {'id': 'F2', 'fingerprint': 'fp-declined', 'claim': 'toast only', 'severity': 'Minor', 'finders': ['Standards'],
             'sites': ['lib/b.ts:10'], 'status': 'open'},
            {'id': 'F3', 'claim': 'spec status', 'severity': 'Minor', 'status': 'fixed', 'statusNote': 'Addressed in f7bcc29'},
            {'id': 'F4', 'fingerprint': 'fp-dismissed', 'claim': 'naming', 'severity': 'Trivial', 'status': 'dismissed',
             'statusNote': 'house style'},
            {'id': 'F5', 'fingerprint': 'fp-old-post', 'claim': 'posted before the marker', 'severity': 'Minor', 'status': 'open',
             'sites': ['lib/e.ts:7'], 'threadId': 'T-lib/e.ts-7'},
        ],
        'refuted': [{'claim': 'the error is swallowed', 'sites': ['lib/c.ts:195'], 'finders': ['General'], 'reason': 'logged by the caller'}]}})
    fake_repo(T, 'api-server', {'claude_kit-branch.json': {'lastReviewed': 'def', 'reviewedAt': '2026-10-24T11:00:00+00:00',
                                                               'scope': 'quick', 'findings': []}})

    spec = importlib.util.spec_from_file_location('ledger', LEDGER_PY)
    L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)

    led = L.load()
    n = L.sync(led)
    app = led['runs'].get('acme-web:claude_offer-check', {})
    kit = led['runs'].get('acme-api:claude_kit-branch', {})
    checks = [
        ('sync reads both repos', n == 2 and app and kit),
        ('branch guessed from the state file name', app.get('branch') == 'claude/offer-check'),
        ('folder api-server is recorded as acme-api', kit.get('repo') == 'acme-api'),
        ("the profile supplies the GitHub repo", app.get('github') == 'acme/web'),
        ('a mode written into scope is kept as mode', kit.get('mode') == 'quick'),
        ('fixed and dismissed are normalized', app['findings'].get('fp-dismissed', {}).get('status') == 'declined'
         and any(f['status'] == 'fixed' for f in app['findings'].values())),
    ]

    threads = {('acme/web', 172): [
        thread('fp-fixed', 'lib/a.ts', 40, [('fofiu', 'finding'), ('fofiu', '✅ Addressed in 1234567')], resolved=True),
        thread('fp-declined', 'lib/b.ts', 10, [('fofiu', 'finding'), ('fofiu', 'design.md allows a toast here')]),
        thread(None, 'lib/c.ts', 200, [('coderabbitai', 'Missing log. Return value hides the error.')], fixed=True),
        thread(None, 'lib/a.ts', 45, [('coderabbitai', 'Same voice issue.')], fixed=True),
        thread(None, 'lib/d.ts', 5, [('gemini-code-assist', 'Style nit.'), ('fofiu', 'No: house style.')]),
        thread(None, 'lib/e.ts', 7, [('fofiu', '1. posted before the marker'), ('fofiu', 'Addressed in 89abcde')], fixed=True),
        thread(None, 'lib/f.ts', 3, [('coderabbitai', '**<picture><img src="x"></picture> Minor** · **Data Integrity & Integration** · **Quick win** <details><summary>Supported by static analysis</summary>**Script executed in the sandbox**</details> **Guard the empty list before reading it.** The loop')]),
    ]}
    prs = {'acme-web': {'number': 172, 'state': 'MERGED', 'url': 'u'}, 'acme-api': {'number': 9, 'state': 'OPEN', 'url': 'v'}}
    done = L.settle(led, pr_fn=lambda repo, run: prs.get(repo), threads_fn=lambda repo, pr: threads.get((repo, pr), []))
    fs = app['findings']
    others = app.get('settled', {}).get('others', [])
    checks += [
        ('settle reads the merged PR only', done == 1 and 'settled' not in kit),
        ('our thread with "Addressed in" is fixed', fs['fp-fixed'].get('outcome') == 'fixed'),
        ('our thread with a reply and no fix is declined', fs['fp-declined'].get('outcome') == 'declined'),
        ('a status set in the state wins over the thread', fs['fp-dismissed'].get('outcome') == 'declined'),
        ('four other-reviewer threads recorded', len(others) == 4),
        ('an old post without a marker is matched by its thread id', fs['fp-old-post'].get('outcome') == 'fixed'),
        ("a CodeRabbit title is its bold line", any(o['title'] == 'Guard the empty list before reading it.' for o in others)),
        ('a fixed bot thread near our site is not a miss', any(o['path'] == 'lib/a.ts' and o['nearOurs'] for o in others)),
        ('a fixed bot thread away from ours is a miss', any(o['path'] == 'lib/c.ts' and not o['nearOurs'] and o['outcome'] == 'fixed' for o in others)),
        ('a miss beside a refuted candidate is marked', any(o['path'] == 'lib/c.ts' and o['nearRefuted'] for o in others)
         and not any(o['path'] == 'lib/d.ts' and o['nearRefuted'] for o in others)),
    ]

    L.save(led)
    led2 = L.load()
    L.sync(led2)  # a later sync must keep what settle learned
    checks.append(('sync keeps settled outcomes', led2['runs']['acme-web:claude_offer-check']['findings']['fp-fixed'].get('outcome') == 'fixed'))
    r = L.report(led2)
    checks += [
        ('report counts outcomes', r['outcomes'].get('fixed') == 3 and r['outcomes'].get('declined') == 2),
        ('report lists exactly one miss', len(r['misses']) == 1 and 'lib/c.ts:200' in r['misses'][0]),
        ('report scores finders', r['byFinder'].get('Standards', {}).get('declined') == 1 and r['byFinder'].get('Claims', {}).get('fixed') == 1),
        ('report groups by skill version', r['byVersion'].get('8', {}).get('misses') == 1),
        ('report counts settled PRs since the last note', r['settledSinceLastNote'] == 1),
        ('report marks the miss a check refuted', r['missesRefuted'] == 1 and 'a check refuted' in r['misses'][0]),
        ('old version labels map to the skill VERSION', [L.version_of(v) for v in ('1.0.3', 'monogram 1.1.1', 'monogram-1.1.1', '11', None)]
         == ['9', '11', '11', '11', None]),
        ('finder labels map to the finders they name', [L.finder_names(n) for n in ('Claims+Standards', 'Performance and quality',
         'Security and performance', 'Perf', 'General A', 'General-MCP', 'Contracts (app review)', 'Contracts/Design',
         'scanner', 'push review 0e4a30ce', 'self review', None)]
         == [['Claims', 'Standards'], ['Performance'], ['Security', 'Performance'], ['Performance'], ['General'], ['General'],
             ['Contracts'], ['Contracts', 'Design'], ['scanner'], ['other'], ['other'], [None]]),
        ('report counts misses by the reviewer that raised them', r['missesBy'] == {'coderabbitai': 1}),
        ('a rate counts findings with no outcome beside it', L.rate({'fixed': 3, 'declined': 1, 'open': 2}) == '3/4 fixed, 2 no outcome'
         and L.rate({'open': 2}) == 'no outcomes yet, 2 no outcome'),
    ]
    out = subprocess.run([sys.executable, LEDGER_PY, 'report'], capture_output=True, text=True)
    checks.append(('report prints', out.returncode == 0 and 'Misses' in out.stdout and '1 PRs settled' in out.stdout))
    subprocess.run([sys.executable, LEDGER_PY, 'note', 'v9: test'], capture_output=True, text=True)
    checks.append(('a note resets the count', L.report(L.load())['settledSinceLastNote'] == 0))

    failed = 0
    for name, ok in checks:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    shutil.rmtree(T, ignore_errors=True)
    print(f'\n{len(checks) - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
