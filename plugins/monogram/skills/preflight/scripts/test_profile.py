#!/usr/bin/env python3
"""Tests for profile.py against the bundled example profile, with fake repos in a temp folder.

Usage: python3 test_profile.py
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = os.path.join(os.path.dirname(HERE), 'profiles')
os.environ['PREFLIGHT_PROFILES'] = BUNDLED  # only the bundled profiles, whatever the machine has
sys.path.insert(0, HERE)
import profile as prof  # noqa: E402


def repo(path, origin=None):
    os.makedirs(path)
    subprocess.run(['git', 'init', '-q', path], check=True)
    if origin:
        subprocess.run(['git', '-C', path, 'remote', 'add', 'origin', origin], check=True)
    return path


def main():
    T = tempfile.mkdtemp(prefix='profile-test-')
    api = repo(os.path.join(T, 'api-server'), 'git@github.com:acme/api.git')
    web = repo(os.path.join(T, 'web'), 'https://github.com/acme/web')
    renamed = repo(os.path.join(T, 'my-web-clone'), 'https://github.com/acme/web.git')
    other = repo(os.path.join(T, 'widgets'), 'https://github.com/someone/widgets.git')
    offline = repo(os.path.join(T, 'case'), '/nonexistent/offline/api-server.git')
    with open(os.path.join(other, '.gitattributes'), 'w') as f:
        f.write('gen/*.ts linguist-generated\n*.md text\n')
    a, o, r, c = prof.detect(api), prof.detect(other), prof.detect(renamed), prof.detect(offline)
    gen = prof.generated_regexes(o, other)
    os.makedirs(os.path.join(T, 'by-name'))  # a teammate who cloned the api under its repo name, not the profile's folder
    web2 = repo(os.path.join(T, 'by-name', 'web'), 'https://github.com/acme/web')
    api2 = repo(os.path.join(T, 'by-name', 'acme-api'), 'git@github.com:acme/api.git')
    checks = [
        ('a GitHub slug finds the profile repo', a.profile and a.profile['name'] == 'example' and a.repo == 'acme-api'),
        ('a clone in a folder of another name still matches by slug', r.repo == 'acme-web' and r.github == 'acme/web'),
        ('an offline copy matches by the folder name in its origin', c.repo == 'acme-api' and c.github == 'acme/api'),
        ('an unknown repo has no profile', o.profile is None and o.repo == 'widgets' and o.github == 'someone/widgets'),
        ('a gated profile gates, no profile does not', prof.gated(a) and not prof.gated(o)),
        ('by_slug finds a gated repo, case-insensitively', prof.gated(prof.by_slug('ACME/web')) and prof.by_slug('someone/widgets') is None),
        ('siblings are the profile repos next to this one', prof.siblings(api, a) == [web]),
        ('a sibling cloned under its repo name is found too', prof.siblings(web2, prof.detect(web2)) == [api2]),
        ('no profile, no siblings', prof.siblings(other, o) == []),
        ('generated: lockfiles always, .gitattributes too', any(g.search('bun.lock') for g in gen)
         and any(g.search('gen/client.ts') for g in gen) and not any(g.search('README.md') for g in gen)),
        ("generated: the repo's own patterns from the profile", any(g.search('openapi/client/x.ts') for g in prof.generated_regexes(a))),
        ('signals: the profile overrides a default', 'src/handlers/' in prof.signals(a)['security'] and 'src/handlers/' not in prof.signals(o)['security']),
        ("section: this repo's notes only", 'api-server' in prof.section(a, 'repos.md', 'acme-api')
         and 'React web app' not in prof.section(a, 'repos.md', 'acme-api')),
        ('section: the all-repos section by its first word', 'error code added' in prof.section(a, 'checks.md', 'All')),
        ('section: nothing without a profile', prof.section(o, 'checks.md', 'widgets', 'All') == ''),
    ]

    # A user profile folder comes first, and a broken profile there is skipped.
    user = os.path.join(T, 'user-profiles')
    def write(folder, body):
        os.makedirs(os.path.join(user, folder))
        with open(os.path.join(user, folder, 'profile.json'), 'w') as f:
            f.write(body if isinstance(body, str) else json.dumps(body))
    write('mine', {'name': 'mine', 'repos': {'widgets': {'github': 'someone/widgets'}}})
    write('shadow', {'name': 'example', 'repos': {}})  # same name as the bundled one, with no repos
    write('broken', '{not json')
    os.environ['PREFLIGHT_PROFILES'] = os.pathsep.join([user, BUNDLED])
    checks += [
        ('a profile in the user folder is found', prof.detect(other).profile and prof.detect(other).profile['name'] == 'mine'),
        ('the first folder wins a name clash', prof.detect(api).profile is None),
        ('a broken profile is skipped, not fatal', isinstance(prof.load_all(), list)),
    ]
    os.environ['PREFLIGHT_PROFILES'] = BUNDLED

    common = os.path.join(T, 'common')
    os.makedirs(os.path.join(common, 'subcore-review'))
    open(os.path.join(common, 'subcore-review', 'b.json'), 'w').write('{}')
    checks += [
        ('state: an old file is still found', prof.state_file(common, 'b').endswith('subcore-review/b.json')),
        ('state: a new one goes in the preflight folder', prof.state_file(common, 'new').endswith('preflight/new.json')),
    ]
    failed = 0
    for name, ok in checks:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    shutil.rmtree(T, ignore_errors=True)
    print(f'\n{len(checks) - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
