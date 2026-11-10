"""Shared results: a profile with "sharedResults": true keeps every reviewer's results in the profile's own repo.

The profile's folder is then a clone of a repo the team shares. After `ledger.py sync` or `settle`, each of this
reviewer's reviews of the profile's repos is written to <profile>/results/<login>/<repo>/<branch key>.json, then
committed and pushed. A reviewer writes only their own folder, so two people never change the same file, and only
that folder is committed, so a profile edit in progress is never pushed for them. `ledger.py report`, run in one of
the profile's repos, pulls and reports on everyone's files.

The login is the reviewer's GitHub login (`gh api user`), or PREFLIGHT_LOGIN. Local paths stay out of the files.
A pull or push that fails (offline, no access, a conflict) is reported, and the commit waits for the next sync.
"""
import glob, json, os, re, subprocess

import profile as prof

LOCAL_ONLY = ('stateFile', 'repoRoot')
TIMEOUT = 60  # seconds per git or gh call: a hung credential prompt must not hold up the review


def run(args, cwd=None):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT,
                           env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout if r.returncode == 0 else r.stderr or r.stdout).strip()


def git(d, *args):
    return run(['git', '-C', d, *args])


def login():
    if os.environ.get('PREFLIGHT_LOGIN'):
        return os.environ['PREFLIGHT_LOGIN']
    ok, out = run(['gh', 'api', 'user', '-q', '.login'])
    return out if ok and out else None


def sharing():
    return [p for p in prof.load_all() if p.get('sharedResults')]


def slugs(p):
    return {(r.get('github') or '').lower() for r in p.get('repos', {}).values()} - {''}


def safe(name):
    return re.sub(r'[^\w.@-]+', '_', str(name))


def write(path, text):
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)
    return True


def push(d, mine):
    """Commit this reviewer's folder, then pull and push. Only the network calls that are needed."""
    if not os.path.isdir(os.path.join(d, '.git')):
        return {'pushed': False, 'error': 'the profile folder is not a git clone'}
    git(d, 'add', '--', mine)
    if not git(d, 'diff', '--cached', '--quiet', '--', mine)[0]:
        ok, msg = git(d, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m',
                      f'Review results from {os.path.basename(mine)}', '--', mine)
        if not ok:
            return {'pushed': False, 'error': f'commit failed: {msg}'}
    ok, ahead = git(d, 'rev-list', '--count', '@{u}..HEAD')
    if ok and ahead == '0':
        return {'pushed': False}
    ok, msg = git(d, 'pull', '--rebase', '--autostash', '-q')
    if not ok:
        git(d, 'rebase', '--abort')
        return {'pushed': False, 'error': f'pull failed: {msg}'}
    ok, msg = git(d, 'push', '-q')
    return {'pushed': ok} if ok else {'pushed': False, 'error': f'push failed: {msg}'}


def publish(led):
    """Write this reviewer's runs into every profile that shares results, and push them."""
    profiles = sharing()
    if not profiles:
        return {}
    who = login()
    if not who:
        return {p['name']: {'error': 'no GitHub login: run `gh auth login`, or set PREFLIGHT_LOGIN'} for p in profiles}
    out = {}
    for p in profiles:
        repos, mine, written = slugs(p), os.path.join(p['dir'], 'results', safe(who)), 0
        for key, r in led['runs'].items():
            if (r.get('github') or '').lower() not in repos:
                continue
            body = {**{k: v for k, v in r.items() if k not in LOCAL_ONLY}, 'by': who}
            path = os.path.join(mine, safe(r['repo']), safe(key.split(':', 1)[-1]) + '.json')
            written += write(path, json.dumps(body, indent=1, sort_keys=True) + '\n')
        out[p['name']] = {'written': written, **push(p['dir'], mine)}
    return out


def team(p):
    """Everyone's runs in a sharing profile, after a pull. A failed pull still reports on the files already here."""
    ok, msg = git(p['dir'], 'pull', '--rebase', '--autostash', '-q')
    if not ok:
        git(p['dir'], 'rebase', '--abort')
    runs = {}
    for f in sorted(glob.glob(os.path.join(p['dir'], 'results', '*', '*', '*.json'))):
        try:
            with open(f) as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            continue
        r.setdefault('findings', {})
        runs[os.path.relpath(f, os.path.join(p['dir'], 'results'))[:-5]] = r
    return {'version': 1, 'runs': runs, 'notes': []}, (None if ok else f'pull failed, so this is the copy on this machine: {msg}')
