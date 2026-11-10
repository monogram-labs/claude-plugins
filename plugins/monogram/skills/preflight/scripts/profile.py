"""Project profiles: what Preflight knows about a family of repos beyond what each repo says about itself.

Profiles are read from ~/.claude/preflight/profiles/ first, then from the plugin's own profiles/ folder,
so a private profile never has to live in the plugin. A name found in both is taken from the first.
PREFLIGHT_PROFILES (folders joined by the OS path separator) replaces both, for tests.

A profile is a folder <profiles>/<name>/:
- profile.json: its repos (GitHub slug, folder, generated paths), extra generated globs, signal
  patterns, whether the PR gate holds `gh pr create` in its repos, and whether the team shares
  review results through the profile's own repo ("sharedResults", see shared.py);
- repos.md: notes per repo (guidance files, gates, mirrors), under "## <repo>" headings;
- checks.md: extra checks per repo, the same way;
- never-flag.md: what not to report, the same way, plus "## All repos".

A repo with no profile gets the defaults: guidance from its own rules files (AGENTS.md, CLAUDE.md, CONTRIBUTING, other tools' rules),
generated files from lockfiles and .gitattributes, no sibling repos, and no PR gate.
"""
import fnmatch, glob, json, os, re, subprocess
from collections import namedtuple

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_PROFILES = os.path.expanduser('~/.claude/preflight/profiles')
BUNDLED_PROFILES = os.path.join(SKILL_DIR, 'profiles')
STATE_DIRS = ('preflight', 'subcore-review')  # where reviews keep state in .git; the old name is still read

DEFAULT_GENERATED = [r'(^|/)bun\.lockb?$', r'(^|/)package-lock\.json$', r'(^|/)pnpm-lock\.yaml$', r'(^|/)yarn\.lock$',
                     r'(^|/)(Cargo|poetry|Gemfile|composer)\.lock$', r'(^|/)go\.sum$', r'\.snap$', r'\.min\.(js|css)$',
                     r'(^|/)dist/', r'\.generated\.']
DEFAULT_GLOBS = ['**/*.lock', '**/bun.lock', '**/package-lock.json', '**/pnpm-lock.yaml', '**/go.sum', '**/dist/**',
                 '**/*.min.js', '**/*.snap']
DEFAULT_SIGNALS = {
    'security': r'(auth|session|middleware|/api/|routes?/|webhook|fetch|signing|secret|token|cors|redirect|permission|policy|migrations?/|\.env)',
    'data': r'(migrations?/|schema|/db/|models?/|/store)',
    'performance': r'(realtime|stream|worker|queue|hooks/use-|components/.*(list|table|grid|feed))',
    'contracts': r'(specs?/|adrs?/|CHANGELOG\.md$|\.changeset/|/api/|routes?/|openapi|\.proto$|package\.json$|types?\.ts$)',
    'docs': r'(\.mdx?$|README|AGENTS\.md|CLAUDE\.md|CONTRIBUTING)',
    'dependencies': r'(^|/)(package\.json|bun\.lockb?|requirements[^/]*\.txt|pyproject\.toml|go\.mod|Cargo\.toml)$',
    'ci': r'^\.github/',
    'shell': r'\.sh$',
    'client': r'(components/|app/.*\.tsx$|hooks/|pages/)',
}

Match = namedtuple('Match', 'profile repo entry github')


def git(root, *args):
    r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ''


def slug_of(url):
    m = re.search(r'github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$', url or '')
    return f'{m.group(1)}/{m.group(2)}' if m else None


def profile_dirs():
    env = os.environ.get('PREFLIGHT_PROFILES')
    return [d for d in env.split(os.pathsep) if d] if env else [USER_PROFILES, BUNDLED_PROFILES]


def load_all():
    out, names = [], set()
    for d in profile_dirs():
        for f in sorted(glob.glob(os.path.join(d, '*', 'profile.json'))):
            try:
                with open(f) as fh:
                    p = json.load(fh)
            except (OSError, ValueError):
                continue  # a broken profile is skipped, not fatal: the review falls back to the defaults
            if p.get('name') in names:
                continue
            names.add(p.get('name'))
            p['dir'] = os.path.dirname(f)
            out.append(p)
    return out


def detect(root):
    """The profile and repo entry for the checkout at root, matched by GitHub slug, then by name."""
    origin = git(root, 'remote', 'get-url', 'origin')
    slug = slug_of(origin)
    from_origin = re.sub(r'\.git$', '', origin.rstrip('/').rsplit('/', 1)[-1]) if origin else ''
    folder = os.path.basename(os.path.abspath(root))
    for p in load_all():
        for name, r in p.get('repos', {}).items():
            if slug and (r.get('github') or '').lower() == slug.lower():
                return Match(p, name, r, slug)
        for name, r in p.get('repos', {}).items():
            if from_origin in (name, r.get('folder')) or (not slug and folder in (name, r.get('folder'))):
                return Match(p, name, r, slug or r.get('github'))
    return Match(None, from_origin or folder, {}, slug)


def by_slug(slug):
    for p in load_all():
        for name, r in p.get('repos', {}).items():
            if (r.get('github') or '').lower() == (slug or '').lower():
                return Match(p, name, r, r['github'])
    return None


def gated(match):
    return bool(match and match.profile and match.profile.get('gate'))


def generated_regexes(match, root=None):
    pats = DEFAULT_GENERATED + list(match.entry.get('generated', []))
    if root:  # .gitattributes: path linguist-generated
        try:
            with open(os.path.join(root, '.gitattributes')) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) > 1 and any(a in ('linguist-generated', 'linguist-generated=true') for a in parts[1:]):
                        pats.append(fnmatch.translate(parts[0].lstrip('/')).replace(r'\Z', '$'))
        except OSError:
            pass
    return [re.compile(p) for p in pats]


def generated_globs(match):
    return DEFAULT_GLOBS + list((match.profile or {}).get('generatedGlobs', []))


def signals(match):
    return {**DEFAULT_SIGNALS, **(match.profile or {}).get('signals', {})}


def siblings(root, match):
    """The profile's other repos that sit next to this checkout, under their folder or their repo name. None without a profile."""
    if not match.profile:
        return []
    parent = os.path.dirname(os.path.abspath(root))
    out = []
    for name, r in match.profile.get('repos', {}).items():
        if name == match.repo:
            continue
        for folder in dict.fromkeys((r.get('folder', name), name)):
            path = os.path.join(parent, folder)
            if os.path.abspath(path) != os.path.abspath(root) and os.path.isdir(os.path.join(path, '.git')):
                out.append(path)
                break
    return out


def section(match, filename, *titles):
    """The '## <title>' sections of a profile file, joined, for each title that has one."""
    if not match.profile:
        return ''
    try:
        with open(os.path.join(match.profile['dir'], filename)) as f:
            text = f.read()
    except OSError:
        return ''
    parts, out = re.split(r'(?m)^## ', text), []
    for t in titles:
        hit = next((p for p in parts[1:] if p.split('\n', 1)[0].strip().split(' ', 1)[0] == t), None)
        if hit:
            out.append('### ' + hit.strip())
    return '\n\n'.join(out)


def state_dir(common):
    return os.path.join(common, STATE_DIRS[0])


def state_file(common, key):
    """Where a branch's state is: the new folder first, then the old one."""
    for d in STATE_DIRS:
        f = os.path.join(common, d, f'{key}.json')
        if os.path.exists(f):
            return f
    return os.path.join(common, STATE_DIRS[0], f'{key}.json')
