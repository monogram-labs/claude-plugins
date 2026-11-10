#!/usr/bin/env python3
"""The review ledger: what Preflight posted, what happened to it, and what it missed.

Usage:
  ledger.py sync                      copy the review state files of this repo, and of every repo the
                                      ledger has seen and its profile's siblings, into the ledger
  ledger.py settle [--include-open]   for each reviewed PR that is merged or closed, read its threads
                                      (gh, read-only): which of our findings were fixed, declined or
                                      ignored, and which other reviewers' findings were fixed
  ledger.py report [--since DATE] [--json] [--mine]
  ledger.py note "TEXT"               record a change to the skill, so reports compare before and after

A finding another reviewer raised, that the author fixed, and that sits nowhere near one of ours
is a miss: the thing to learn from. The ledger lives at ~/.claude/preflight/ledger.json
(PREFLIGHT_LEDGER overrides it; an older ~/.claude/subcore-review/ledger.json is read once and moved).
PREFLIGHT_REPOS (paths joined by the OS path separator) replaces the repo discovery, for tests.

In a profile with "sharedResults": true (shared.py), sync and settle also push this reviewer's runs
to the profile's repo, and report, run in one of its repos, covers everyone's runs unless --mine.
"""
import datetime, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from threads import title_of  # noqa: E402
import profile as prof  # noqa: E402
import shared  # noqa: E402
LEDGER = os.environ.get('PREFLIGHT_LEDGER') or os.path.expanduser('~/.claude/preflight/ledger.json')
OLD_LEDGER = os.path.expanduser('~/.claude/subcore-review/ledger.json')
STATUS = {'addressed': 'fixed', 'fixed': 'fixed', 'dismissed': 'declined', 'declined': 'declined',
          'open': 'open', 'obsolete': 'obsolete'}
NEAR = 10  # lines: another reviewer's thread this close to one of our sites counts as the same spot
FINDERS = ('General', 'Contracts', 'Security', 'Performance', 'Design', 'Standards', 'Claims')
# Runs before scope.py printed skillVersion wrote the plugin's version instead. Plugin release -> skill VERSION.
PLUGIN_VERSIONS = {'1.0.0': '9', '1.0.1': '9', '1.0.2': '9', '1.0.3': '9', '1.0.4': '10', '1.1.0': '10', '1.1.1': '11'}


def version_of(v):
    v = re.sub(r'^(?:monogram|elegant)[\s-]*', '', str(v or '').strip())
    return PLUGIN_VERSIONS.get(v, v) or None


def finder_names(name):
    """The finders a label names. Runs wrote "Claims+Standards", "Perf", "General A", "Contracts (app review)"."""
    if not name:
        return [None]
    out = []
    for part in re.split(r'\s*(?:\+|,|\band\b)\s*', re.sub(r'\s*\(.*?\)', '', name)):
        word = re.split(r'[\s-]', part.strip())[0].lower()
        hit = next((f for f in FINDERS if len(word) >= 4 and f.lower().startswith(word)), None)
        if hit and hit not in out:
            out.append(hit)
    return out or [name]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def load():
    for path in (LEDGER, OLD_LEDGER if not os.environ.get('PREFLIGHT_LEDGER') else None):
        if path and os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return {'version': 1, 'runs': {}, 'notes': []}


def save(led):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    tmp = f'{LEDGER}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        json.dump(led, f, indent=1)
    os.replace(tmp, LEDGER)


def git(path, *args):
    r = subprocess.run(['git', '-C', path, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ''


def guess_branch(stem):
    # scope.py writes the state as <branch with / turned into _>.json; most branches here are claude/...
    return None if stem.startswith('detached-') else re.sub(r'^claude_', 'claude/', stem)


def sites_of(f):
    out = []
    for s in f.get('sites') or []:
        m = re.match(r'([^:\s]+):(\d+)', s)
        if m:
            out.append((m.group(1), int(m.group(2))))
    return out


def repo_roots(led):
    """This checkout, every repo the ledger has seen, and their profiles' siblings."""
    if os.environ.get('PREFLIGHT_REPOS'):
        return [p for p in os.environ['PREFLIGHT_REPOS'].split(os.pathsep) if p]
    roots = [git(os.getcwd(), 'rev-parse', '--show-toplevel')]
    for r in led['runs'].values():
        sf = r.get('stateFile') or ''
        roots.append(r.get('repoRoot') or (os.path.dirname(os.path.dirname(os.path.dirname(sf))) if '/.git/' in sf else ''))
    out = []
    for root in roots:
        if root and os.path.isdir(root):
            for p in [root] + prof.siblings(root, prof.detect(root)):
                p = os.path.abspath(p)
                if p not in out:
                    out.append(p)
    return out


def sync(led):
    seen = 0
    for path in repo_roots(led):
        match = prof.detect(path)
        repo = match.repo
        common = git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        files = [f for d in prof.STATE_DIRS for f in sorted(glob.glob(os.path.join(common, d, '*.json')))] if common else []
        for sf in files:
            try:
                with open(sf) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            stem = os.path.basename(sf)[:-5]
            run = led['runs'].setdefault(f'{repo}:{stem}', {'repo': repo, 'findings': {}})
            scope = data.get('scope')
            run.update({k: v for k, v in {
                'stateFile': sf, 'repoRoot': path, 'github': match.github or run.get('github'), 'branch': data.get('branch') or run.get('branch') or guess_branch(stem),
                'pr': data.get('pr') or run.get('pr'), 'lastReviewed': data.get('lastReviewed'),
                'reviewedAt': data.get('reviewedAt'), 'startedAt': data.get('startedAt'),
                'mode': data.get('mode') or (scope if scope not in ('committed', 'working-tree') else None),
                'skillVersion': version_of(data.get('skillVersion')), 'finders': data.get('finders'),
                'refuted': [{k: c.get(k) for k in ('claim', 'sites', 'finders', 'reason')} for c in data.get('refuted') or []] or None,
            }.items() if v is not None})
            for i, f in enumerate(data.get('findings') or []):
                fid = f.get('fingerprint') or f"{f.get('id') or i}:{(f.get('claim') or '')[:40]}"
                old = run['findings'].get(fid, {})
                run['findings'][fid] = {**old, **{k: f.get(k) for k in (
                    'id', 'fingerprint', 'claim', 'severity', 'category', 'finders', 'sites', 'threadId', 'statusNote')},
                    'status': STATUS.get(str(f.get('status')).lower(), 'open')}
            seen += 1
    return seen


def thread_outcome(t):
    if t.get('fixedMark') or (t.get('isResolved') and t.get('isOutdated')):
        return 'fixed'
    if t.get('isResolved'):
        return 'fixed'  # resolved without a word: the author treated it as done
    return 'declined' if len(t.get('comments') or []) > 1 else 'no-reply'


def gh_pr(repo, run):
    fields, slug = 'number,state,mergedAt,url', run.get('github')
    if not slug:
        return None
    if run.get('pr'):
        args = ['pr', 'view', str(run['pr']), '--repo', slug, '--json', fields]
    elif run.get('branch'):
        args = ['pr', 'list', '--repo', slug, '--head', run['branch'], '--state', 'all', '--json', fields, '--limit', '1']
    else:
        return None
    r = subprocess.run(['gh', *args], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    data = json.loads(r.stdout or 'null')
    return (data[0] if data else None) if isinstance(data, list) else data


def settle(led, include_open=False, pr_fn=gh_pr, threads_fn=None):
    if threads_fn is None:
        from threads import list_threads as threads_fn
    done = 0
    for key, run in led['runs'].items():
        if run.get('settled', {}).get('prState') in ('MERGED', 'CLOSED'):
            continue
        pr = pr_fn(run['repo'], run)
        if not pr:
            run['settled'] = {'at': now(), 'prState': 'none'}
            continue
        run['pr'] = pr['number']
        if pr['state'] == 'OPEN' and not include_open:
            continue
        threads = threads_fn(run['github'], pr['number'])
        ids = {f.get('threadId') for f in run['findings'].values()} - {None}
        mine = [t for t in threads if t.get('ours') or t['id'] in ids]  # older posts carry no marker, only a threadId
        ours = {t.get('fingerprint') or t['id']: t for t in mine}
        spots = [s for f in run['findings'].values() for s in sites_of(f)] + [(t['path'], t['line'] or 0) for t in ours.values()]
        refuted = [s for c in run.get('refuted') or [] for s in sites_of(c)]
        near = lambda t, sites: any(p == t['path'] and abs((t['line'] or 0) - l) <= NEAR for p, l in sites)
        for f in run['findings'].values():
            t = ours.get(f.get('fingerprint')) or next((x for x in mine if x['id'] == f.get('threadId')), None)
            if t:
                f['thread'] = thread_outcome(t)
            f['outcome'] = f['status'] if f['status'] != 'open' else f.get('thread', 'open')
        others = []
        for t in threads:
            if t in mine:
                continue
            first = (t.get('comments') or [{}])[0]
            others.append({'by': first.get('author'), 'path': t['path'], 'line': t['line'], 'outcome': thread_outcome(t),
                           'title': t.get('title') or title_of(first.get('body')),
                           'nearOurs': near(t, spots), 'nearRefuted': near(t, refuted)})
        run['settled'] = {'at': now(), 'prState': pr['state'], 'url': pr.get('url'), 'others': others}
        done += 1
    return done


def report(led, since=None):
    runs = [r for r in led['runs'].values() if not since or (r.get('reviewedAt') or '') >= since]
    out = {'reviews': len(runs), 'settled': sum(r.get('settled', {}).get('prState') in ('MERGED', 'CLOSED') for r in runs),
           'outcomes': {}, 'byVersion': {}, 'byFinder': {}, 'bySeverity': {}, 'byReviewer': {}, 'misses': [], 'missesRefuted': 0,
           'declined': []}
    def bump(table, name, outcome):
        row = table.setdefault(name or 'unrecorded', {})
        row[outcome] = row.get(outcome, 0) + 1
    for r in runs:
        ver = version_of(r.get('skillVersion')) or 'unrecorded'
        bump(out['byVersion'], ver, 'reviews')
        if r.get('by'):  # only shared runs name their reviewer
            bump(out['byReviewer'], r['by'], 'reviews')
        for f in r['findings'].values():
            o = f.get('outcome') or f['status']
            out['outcomes'][o] = out['outcomes'].get(o, 0) + 1
            bump(out['byVersion'], ver, o)
            if r.get('by'):
                bump(out['byReviewer'], r['by'], o)
            bump(out['bySeverity'], f.get('severity'), o)
            for name in dict.fromkeys(n for x in f.get('finders') or [None] for n in finder_names(x)):
                bump(out['byFinder'], name, o)
            if o == 'declined':
                out['declined'].append(f"{r['repo']}#{r.get('pr')}: {f.get('claim')} ({f.get('statusNote') or 'declined on the thread'})")
        for t in r.get('settled', {}).get('others', []):
            if t['outcome'] == 'fixed' and not t['nearOurs']:
                bump(out['byVersion'], ver, 'misses')
                out['missesRefuted'] += bool(t.get('nearRefuted'))
                mark = ' [a check refuted a candidate here]' if t.get('nearRefuted') else ''
                out['misses'].append(f"{r['repo']}#{r.get('pr')} {t['by']} {t['path']}:{t['line']}{mark}: {t['title']}")
    last = max((n['at'] for n in led['notes']), default='')
    out['settledSinceLastNote'] = sum(r.get('settled', {}).get('at', '') > last and r['settled'].get('prState') in ('MERGED', 'CLOSED') for r in runs)
    out['notes'] = led['notes'][-5:]
    return out


def rate(row):
    fixed, declined = row.get('fixed', 0), row.get('declined', 0)
    return f"{fixed}/{fixed + declined} fixed" if fixed + declined else 'no outcomes yet'


def print_report(r):
    o = r['outcomes']
    if r.get('team'):
        t = r['team']
        n = len(r['byReviewer'])
        print(f"Shared results of the {t['profile']} profile, from {n} reviewer{'' if n == 1 else 's'}." + (f" ({t['warning']})" if t.get('warning') else ''))
    print(f"{r['reviews']} reviews, {r['settled']} on merged or closed PRs. Findings: " +
          (', '.join(f'{v} {k}' for k, v in sorted(o.items())) or 'none') + f" ({rate(o)}).")
    tables = (('By reviewer', 'byReviewer'),) if r['byReviewer'] else ()
    for title, key in tables + (('By skill version', 'byVersion'), ('By finder', 'byFinder'), ('By severity', 'bySeverity')):
        print(f'\n{title}:')
        for name, row in sorted(r[key].items()):
            extra = ''.join(f", {row[k]} {k}" for k in ('reviews', 'misses') if row.get(k))
            print(f'  {name}: {rate(row)}{extra}')
    print(f"\nMisses: other reviewers' findings the author fixed, nowhere near ours ({len(r['misses'])}, "
          f"{r['missesRefuted']} where a check refuted a candidate):")
    print('\n'.join(f'  {m}' for m in r['misses'][-15:]) or '  none yet')
    print(f"\nOur declined findings, candidates for a Never-flag line ({len(r['declined'])}):")
    print('\n'.join(f'  {d}' for d in r['declined'][-10:]) or '  none yet')
    print(f"\n{r['settledSinceLastNote']} PRs settled since the last recorded change to the skill. At 20, act on this report (SKILL.md, Step 7).")


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else ''
    led = load()
    if cmd in ('sync', 'settle'):
        n = sync(led) if cmd == 'sync' else settle(led, include_open='--include-open' in a)
        save(led)
        out = {'synced': n, 'ledger': LEDGER} if cmd == 'sync' else {'settled': n}
        pub = shared.publish(led)
        print(json.dumps({**out, **({'shared': pub} if pub else {})}))
    elif cmd == 'report':
        root = git(os.getcwd(), 'rev-parse', '--show-toplevel')
        p = prof.detect(root).profile if root else None
        team = None
        if p and p.get('sharedResults') and '--mine' not in a:
            team, warning = shared.team(p)
            team['notes'] = led['notes']
            settle(team)  # in memory: PRs that closed since their reviewer last ran settle
        r = report(team or led, a[a.index('--since') + 1] if '--since' in a else None)
        if team:
            r['team'] = {'profile': p['name'], **({'warning': warning} if warning else {})}
        print(json.dumps(r, indent=1)) if '--json' in a else print_report(r)
    elif cmd == 'note' and len(a) > 1:
        led['notes'].append({'at': now(), 'text': a[1]}); save(led); print('noted')
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
