#!/usr/bin/env python3
"""Post Preflight findings to a PR as one review with inline threads.

Usage: post_review.py --repo OWNER/NAME --pr N --head SHA --findings FILE.json [--dry-run]

FILE.json: {"summary": "<markdown for the review body>",
            "findings": [{"fingerprint": "...", "path": "...", "line": 120, "startLine": 110 (optional),
                          "body": "<the finding in report-format markdown>"}]}

- A finding whose lines sit inside the PR diff (right side) becomes an inline comment.
- Any other finding is listed in the review body under "Outside the diff".
- Each comment gets a hidden marker `<!-- preflight:fp=<fingerprint> -->`. A finding whose
  fingerprint already has an open thread on this PR is skipped, so a re-run never duplicates.
- The review is posted with event COMMENT at the given head SHA: it never approves or blocks.
- The review body and every thread start with "[✈️ Preflight]", the reviewer's name. The comments
  still show your GitHub account as the author, because they go through your gh token.
--dry-run prints what would be posted and posts nothing.
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from threads import MARKER, TAG, list_threads, tagged  # noqa: E402


def gh(args, input_text=None):
    r = subprocess.run(['gh', *args], capture_output=True, text=True, input=input_text)
    if r.returncode != 0:
        raise SystemExit(f'gh {" ".join(args[:3])} failed: {r.stderr.strip()[:300]}')
    return r.stdout


def json_pages(text):
    """`gh api --paginate` prints one JSON document per page. Decode each in turn and join their items."""
    dec, i, out = json.JSONDecoder(), 0, []
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i == len(text):
            return out
        page, i = dec.raw_decode(text, i)
        out.extend(page if isinstance(page, list) else [page])


def diff_lines(repo, pr):
    """Right-side line numbers inside each file's hunks, per hunk, for the PR as GitHub sees it."""
    files = json_pages(gh(['api', f'repos/{repo}/pulls/{pr}/files', '--paginate', '--jq', '[.[] | {filename, patch}]']))
    out = {}
    for f in files:
        hunks, cur, n = [], None, 0
        for l in (f.get('patch') or '').split('\n'):
            m = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', l)
            if m:
                cur = set(); hunks.append(cur); n = int(m.group(1)); continue
            if cur is None or l.startswith('-'):
                continue
            cur.add(n); n += 1
        out[f['filename']] = hunks
    return out


FOOTER = ('<sub>Code Preflight, from the monogram plugin, checks every finding against the code before posting. '
          'Reply on a thread to decline one with evidence.</sub>')


def build_review(data, hunks, open_fps, head):
    """The review payload: inline threads for lines in the diff, the rest in the body. Posts nothing."""
    comments, outside, skipped = [], [], []
    for f in data['findings']:
        fp = f['fingerprint']
        if fp in open_fps:
            skipped.append(fp); continue
        body = tagged(f['body']) + '\n\n' + MARKER.format(fp)
        line, start = int(f['line']), int(f.get('startLine') or f['line'])
        hit = next((h for h in hunks.get(f['path'], []) if line in h and start in h), None)
        if hit is not None:
            c = {'path': f['path'], 'line': line, 'side': 'RIGHT', 'body': body}
            if start != line:
                c.update({'start_line': start, 'start_side': 'RIGHT'})
            comments.append(c)
        else:
            outside.append(f)
    summary = re.sub(r'^##\s*Preflight:\s*', '', data['summary'].strip())  # the report's heading becomes a plain line
    n = len(comments) + len(outside)
    summary = f"{TAG} {n} finding{'s' if n != 1 else ''}, each checked against the code\n\n" + summary
    if outside:
        summary += '\n\n<details><summary>Outside the diff (%d)</summary>\n\n' % len(outside)
        summary += '\n\n---\n\n'.join(f"`{f['path']}:{f['line']}`\n\n{f['body'].strip()}\n\n{MARKER.format(f['fingerprint'])}" for f in outside)
        summary += '\n</details>'
    summary += '\n\n' + FOOTER
    return {'commit_id': head, 'event': 'COMMENT', 'body': summary, 'comments': comments}, outside, skipped


def main():
    a = sys.argv[1:]
    repo = a[a.index('--repo') + 1]; pr = int(a[a.index('--pr') + 1])
    head = a[a.index('--head') + 1]; data = json.load(open(a[a.index('--findings') + 1]))
    dry = '--dry-run' in a
    open_fps = {t['fingerprint'] for t in list_threads(repo, pr) if t['ours'] and not t['isResolved']}
    payload, outside, skipped = build_review(data, diff_lines(repo, pr), open_fps, head)
    comments = payload['comments']
    if dry:
        print(json.dumps({'inline': [(c['path'], c.get('start_line'), c['line']) for c in comments],
                          'outside': [(f['path'], f['line']) for f in outside], 'skipped_already_open': skipped,
                          'body_chars': len(payload['body'])}, indent=1))
        return
    if not comments and not outside:
        print(json.dumps({'posted': False, 'reason': 'nothing new to post', 'skipped_already_open': skipped}))
        return
    res = json.loads(gh(['api', f'repos/{repo}/pulls/{pr}/reviews', '-X', 'POST', '--input', '-'], json.dumps(payload)))
    print(json.dumps({'posted': True, 'review': res.get('html_url'), 'inline': len(comments), 'outside': len(outside), 'skipped_already_open': skipped}))


if __name__ == '__main__':
    main()
