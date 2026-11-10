# monogram

**Code Preflight** (Preflight for short) reviews your branch before you open a pull request, and again after each push.

- **Run it:** `/monogram:preflight`, or say "run Preflight", inside any git repo. It reviews your branch's diff against where it split from main, plus uncommitted work. It reads the surrounding code, the tests, the repo's written rules and, for a project with a profile, the sibling repos. Every finding is checked against the code by its own agent before you see it.
- **Cost:** a full review takes about 15 to 20 minutes and uses about 2 to 3 million tokens, mostly in the agents that check each finding. On a plan with a usage limit that is a noticeable share, so run it before you push, not after every edit. A review after a push covers only the new commits and costs less.
- **On GitHub:** once the PR is open, a run posts its findings as one review, and every message starts with `[✈️ Preflight]`. Posts appear under your own GitHub account, because they go through your `gh` login. After a push, it reviews only the new commits and resolves its own threads that a commit fixed.
- **Declining a finding:** reply on its thread with your reason. Preflight re-checks once and leaves the thread open.
- **The PR gate:** in a project whose profile turns it on, `gh pr create` is held until Preflight has reviewed the branch's latest commit. Skip it for one PR with `PREFLIGHT_SKIP=1 gh pr create ...`. Other repos are never held.
- **How it's doing:** ask "how are the reviews doing?" It reports what you fixed, what you declined, and what other reviewers caught that Preflight missed, from `~/.claude/preflight/ledger.json`. Each person's ledger covers their own reviews, unless the team shares results (below).

## Profiles

A profile tells Preflight about a family of repos: where they are, how to test them, which files are generated, which facts must stay in step, extra checks, and what not to flag. Preflight reads profiles from `~/.claude/preflight/profiles/<name>/` first, then from the plugin's `skills/preflight/profiles/`, which holds only a made-up `example`. A team's profile usually lives in a private repo cloned to `~/.claude/preflight/profiles/`, because it describes internal systems.

A repo with no profile still gets a full review. It uses the repo's own written rules (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING`, and the rules files of Cursor, Copilot, Gemini, Windsurf and Cline), treats lockfiles and `.gitattributes`-generated files as generated, and looks at no sibling repos.

To add a project, copy `skills/preflight/profiles/example/` to `~/.claude/preflight/profiles/<name>/`, edit `profile.json` (its repos' GitHub names and folders, and whether the PR gate applies), and rewrite the three Markdown files. Each repo can also keep a checked-in `REVIEW.md` with a "Never flag" section. That file is authoritative for its repo, and CodeRabbit can read it too.

Keep your own profiles private: they describe your systems, including gaps a review should not re-raise.

**Sharing results across a team.** Set `"sharedResults": true` in `profile.json` when the profile's folder is a clone of a repo the team shares. After each review, Preflight writes your results to `results/<your GitHub login>/` in that repo, commits only that folder, and pushes it. Each person writes only their own folder, so nobody's files conflict. Asking "how are the reviews doing?" in one of the profile's repos then reports on everyone's reviews, by reviewer. The files hold findings, file paths and outcomes, not code. A push that fails waits for the next review.

## Credits

Lenses L9 and L10 adapt mattpocock/skills' `code-review`, and the General finder runs obra/superpowers' code-reviewer template. Both are MIT licensed; see `skills/preflight/THIRD_PARTY.md`.
