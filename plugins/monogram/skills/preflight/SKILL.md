---
name: preflight
description: Code Preflight (Preflight for short), a local pre-push and pre-merge code review for any git repo. One review that covers bugs, error handling, edge cases and tests, plus what general reviewers miss — security, performance, the repo's own written rules, docs and contracts across sibling repos, migrations — and verifies every finding against the code before reporting it. A project profile adds that project's repos, checks and rules. Use inside a repo when the user asks to "review this branch", "review my changes", "pre-push review", "is this ready to merge", "re-review since the last push", "security review", or "review the spec" or ADR, "run Preflight" (the name its reviews carry on GitHub) or "run Code Preflight", "/subcore-review" (its old name), and when the user asks how the reviews are doing or to improve the review from its results. Not for replying to or resolving existing PR review comments.
---

# Code Preflight

Built from 2,900 bot findings on 615 PRs of the Subcore repos and the author's reply to each, and from a blind benchmark of six review skills on nine of those PRs. Three rules come from that record:

1. **Trigger and consequence, or no finding.** Say what the code does, the realistic sequence that breaks it, and what the user or the data ends up with.
2. **Evidence a second reader can check.** Each finding carries the command or the lines that show it, plus the sibling code, doc line or rule that shows the intended behaviour.
3. **Never re-raise what is settled.** A finding that cites a rule quotes it from the file at the base commit.

`SKILL_DIR` means this skill's folder (shown when the skill loads). Pass absolute paths to subagents: a relative `references/…` path resolves against the repo and finds nothing.

**Profiles.** What Preflight knows about a project beyond the repo itself is its profile: its repos and where they sit, gates, generated paths, mirrors, extra checks and "Never flag" entries (`profile.py` explains the files). Profiles are read from `~/.claude/preflight/profiles/<name>/` first, where a team keeps its own (usually a private repo cloned there), then from `$SKILL_DIR/profiles/`, which holds only `example`. `scope.py` matches the repo to a profile by its GitHub remote and prints `profile`. A repo with no profile is reviewed with the defaults: its own rules files (AGENTS.md, CLAUDE.md, CONTRIBUTING, and other coding tools' rules such as `.cursor/rules/`), generated files from lockfiles and `.gitattributes`, and no sibling repos. To add a project, copy `$SKILL_DIR/profiles/example/` to `~/.claude/preflight/profiles/<name>/` and edit it.

## Step 1: Scope

```bash
cd <repo root> && mkdir -p /tmp/preflight-probes && python3 "$SKILL_DIR/scripts/scope.py" [--mode full|push|spec] [--commits-only] [--base REF] [--offline] [FILE ...] | tee /tmp/preflight-probes/scope-<repo root folder name>.json
```

The saved copy is for `context.py` (Step 2). The scripts act on the current directory, so run them from the repo root. `--offline` skips `git fetch` and the `gh` PR lookup. Without a PR, use the PR title and body the user gives you, or the commit messages.

It prints JSON:
- the repo, and literal `head` and `base` SHAs;
- the PR, if `gh` finds one, including a stacked base;
- the `diffCmd`;
- every changed file, with generated ones marked;
- uncommitted work;
- the size class;
- `signals`, saying which kinds of files changed: security, data, performance, contracts, docs, dependencies, ci, shell, client;
- the state file, and the increment since the last review.

How to use it:
- **No profile** (`profile` is null): say so in one line, and review with the defaults.
- **Use the literal SHAs** in every later command and every subagent prompt. Shell variables do not survive between tool calls.
- **Uncommitted work is reviewed by default.** Say so in one line. Pass `--commits-only` when the user wants only what is committed.
- **Mode:** `push` when an earlier review of this branch exists, `spec` when only specs, ADRs or docs changed, and `full` otherwise. The user's words win; "quick review" means quick mode (Step 3).
- **Full whatever the size.** A small change gets every finder too. In testing, the quick pass (two finders, eight checks) caught half as much on a small PR and saved four minutes. Run quick mode only when the user asks for a quick review.
- **Same as last:** if `increment.sameAsLast` is true, set `lastReviewed` to head in the state file, report the earlier findings' status, and stop.
- **Repo notes:** read `$SKILL_DIR/references/repos.md`, then the repo's section of the profile's `repos.md` (the context file carries both).
- **Intent:** read the commit messages and the PR title and body as claims to check.

Push mode and the state file follow `$SKILL_DIR/references/state.md`.

## Step 2: Gates and scanners

Run the scanners and the brief first: they take seconds, and the finders start from them. Then start the gates in the background (`run_in_background`) and let them run while the finders work.

- **Gates** from the profile's `repos.md`, or with no profile, from the repo's own scripts (`package.json`, a Makefile, the CI workflow): lint, type-check, the nearest tests. Results go on the report's Gates line. A failure the change introduced makes the verdict "needs rework". To tell whether a failure is pre-existing, check CI for the base commit (`gh run list --commit <base>`), or say "not checked at base". Never run a command the repo notes forbid.
- **Scanners:** `python3 "$SKILL_DIR/scripts/scan.py" --base <base> --head <head> [--working-tree] [--online]`. Pass `--online` unless you are offline: it lets `bun audit` reach the npm advisory API.
  - It runs gitleaks, actionlint, zizmor, shellcheck and squawk when they are installed.
  - Otherwise it uses built-in checks: secrets in added lines, migration RLS, grants and `SECURITY DEFINER` hygiene, edits to applied migrations, workflow injection, risky dependencies, and a missing schema regeneration.
  - It runs `bun audit` when dependencies changed.
  - Each hit is a candidate. It goes to Step 4 like any other, and is never reported unverified.
  - Name the scanners that were missing on the report's Scanners line.
- **Brief:** `python3 "$SKILL_DIR/scripts/brief.py" --base <base> --head <head> [--working-tree]`. In about two seconds it writes the groundwork every finder would otherwise redo, and prints its path:
  - the changed functions, types and constants, with their callers and tests;
  - where the changed names, env vars, routes and keys appear in the other repos' main branch;
  - the `REVIEW.md` lines whose globs match the changed paths;
  - the specs and ADRs the change edits, its commits name, or that mention the changed names.

  Pass `--siblings <path,path>` when the other repos are not next to this one, and `--out <file>` to write it somewhere other than the state folder.
- **Context file:** `python3 "$SKILL_DIR/scripts/context.py" --scope /tmp/preflight-probes/scope-<folder>.json --brief <brief path> [--siblings <path,path>] [--probes <folder>] [--pr-note "<title and gist of the body>"]`. It writes, once, everything the finders and checks share: the scope with literal SHAs, this repo's notes from `repos.md`, the "Never flag" entries, the finder rules and return format from `finder.md`, and the checking steps from `verifier.md`. It prints its path. Every finder and check reads it first, so their prompts stay a few lines long. In testing, the main thread spent 11 of a review's 36 minutes writing 16 long check prompts before any check could start.

## Step 3: Find

Launch finder subagents with the Agent tool (`subagent_type: general-purpose`, `effort: "medium"`). Write every prompt first, then send all the finder calls in one message so they run in parallel: launched one by one, five finders lost two minutes in testing. At medium effort, finders found as much as at the usual effort in half the time. Each prompt follows the short template in `$SKILL_DIR/references/finder.md`: the context file's path, the lens ids, and only what is particular to that finder. The lenses are in `$SKILL_DIR/references/lenses.md`, and finders read their own sections there.

| Finder | Runs | Covers |
| --- | --- | --- |
| **General** | always | Bugs, error handling, edge cases, tests, design. This finder performs the review in `$SKILL_DIR/vendor/requesting-code-review/code-reviewer.md` (from obra/superpowers; it scored best in the benchmark) with lenses L1 and L3 added. |
| **Contracts** | always | L2: docs vs code, every copy of a changed fact across this repo and its siblings, rules that contradict each other, API and MCP parity, versions, release placeholders, values across layers, identifiers and keys, external API limits. |
| **Security** | `signals.security`, `signals.data`, `signals.ci`, `signals.dependencies` or `signals.shell` is non-empty, or the user asked for a security review | L6, plus the scanner hits for secrets, migrations, workflows and dependencies. |
| **Performance and quality** | `signals.performance` or `signals.client` is non-empty | L7 (hot paths only) and L8 (code quality, at most 3 candidates). |
| **Design** | spec mode, or the change adds a contract: a route, error code, table or column, state machine, or a rule another repo or a consumer must follow (a peer dependency or version floor counts) | L4. Before calling a rule undefined, check that the spec, its ADRs and the schema don't define it: in testing, most Design candidates were refuted that way. |
| **Standards** | always | L9: every rule in this repo's own guidance files and decision records, walked against the diff, plus code the change adds that nothing uses. |
| **Claims** | always | L10: what the change says about itself (commits, PR text, changeset, migration notes, the spec it names), checked against the code, and what it leaves unsaid. |

Every finder also gets this repo's L5 checks. L5 is not split by area, so give each finder all of them.

Sizing:
- **Large:** split General by area, for example server and client, or one finder per package.
- **Quick** (only when the user asks for one, Step 1): two finders. One is the General finder exactly as in a full review; the other covers L2 and L6, plus L4 when the change adds a contract. Verify at most 8 candidates, and say that it was a quick pass. In testing, a quick pass led by ponytail's checks in place of General caught less than half as much.
- **Push mode:** size by the increment, and include the earlier findings in each finder's prompt.

Finders aim for recall, because Step 4 removes the noise. Each finder has a budget of 30 tool calls and only reads and searches; running code is the verifiers' job (`finder.md`). In testing, the slowest finders took 17 minutes and 80 tool calls each, and every check waited for them.

**Probes.** Verifiers may write throwaway scripts under `/tmp/preflight-probes/<repo>-<head8>/` (one folder per review, so parallel reviews don't collide), never in the repo, and run them with `bun --no-install`, `node`, or `python3 -I`, whichever the repo uses. Finders don't run code. Tell every subagent the folder.
- **Mutation checks:** to mutate code, copy it first (`git archive <head> | tar -x -C /tmp/preflight-probes/<name>`). Never use a worktree or checkout, because the main checkouts are shared.
- **Install resolution:** to test what bun installs, serve stand-in packages from a throwaway registry on 127.0.0.1, on a random free port. Set a scratch `BUN_INSTALL_CACHE_DIR` and `HOME` so the real cache stays clean.

**Cost.** With the context file, medium-effort finders and one round of checks, a review took 14–21 minutes in testing, small or medium. Most of its tokens are cached re-reads of each agent's context, which bill at a fraction of new input. Say so up front when a review will be large.

**A subagent that fails** (an error, a rate limit, an empty answer): retry it once, unchanged. If it fails again, run that pass yourself, or list its candidates as "not verified (failed)". Never treat silence as "nothing found".

## Step 4: Triage and verify

First triage in the main thread:
1. Merge candidates that one fix would resolve together, keeping every site. Two that share a mechanism but need different fixes stay separate, and a candidate that bundles claims needing different fixes is split. A merged candidate takes the highest severity any finder proposed.
2. Drop a candidate in triage only when a "Never flag" entry clearly covers it: same kind of claim, same kind of file, and none of the entry's exceptions apply. The entries come from the repo's `REVIEW.md` (checked in; authoritative for that repo) and `precedents.md` (cross-repo rules, and repo rules for a repo with no `REVIEW.md` yet). In testing, broad matching in triage threw away two real findings. When a match is a judgment call, keep the candidate and let its verifier weigh the entry against the code.
   - The entries that matter for a candidate are the `**` ones plus those whose path glob matches one of its sites. With no `REVIEW.md`, take them from `precedents.md`'s "All repos" section and this repo's own section only. The context file and the brief carry them to the checks.
3. The General finder may return obra's "Declined to judge" list. Promote a line from it only if it names a concrete trigger.
4. Rank by proposed severity. Verify the top 20, and list the rest as "not verified (cap)".

Then verify them in one round, at the usual effort (do not pass `effort`: at medium, checks let through more false findings). Send the checks in batches of at most 12 per message; send the next batch once every check in the last one has returned. The harness runs at most 20 subagents at a time across the whole session, so a larger message fails with "Concurrent subagent limit reached"; retry a launch that fails that way once, after its batch returns.
- **Every candidate gets its own fresh `general-purpose` subagent,** whatever its severity, and it may run code to settle the claim. In testing, one checker shared by several minor candidates threw out real findings.
- **A candidate about a project check with its own procedure** (a profile can give one): the context file's Project checks section carries the procedure, so tell its checker to follow it.

Each check's prompt is short, because the context file holds the scope, the repo notes, the "Never flag" entries and the checking steps:

```
You are a check in a Preflight review of <repo> at <head8>. Read <context file> first: its Scope, Repo
notes, Never flag and Checking sections are your instructions. Then use the brief it names.
Your probe folder: <probe folder>/<candidate id>/.
<Project check with a procedure:> Follow the procedure for <check name> in the context file's Project checks.
Candidate <id>, from the <name> finder, after triage:
<the candidate in the finder return format, with every site>
```

What comes back:
- **Verdicts:** confirmed, refuted (with the reason, plus a backlog note if the problem is real but pre-existing), or unverified.
- **Partial:** a candidate that bundled several claims may be confirmed for only part of them. Report that part.
- **Disagreement:** when two verifiers disagree, trust the one whose evidence is observed.
- **Unverified Major or Critical:** run a second verifier after the round. It gets the first one's evidence and a larger budget, and may run a repro in a scratch copy under `/tmp/preflight-probes/`.

Without the Agent tool (inside a subagent, for example), run the passes yourself in sequence. Re-read the code fresh for each verification, and say in the report that you did this.

## Step 5: Report

Merge confirmed findings that one fix resolves into one finding, keeping every site. Assign each confirmed finding a Category and an Effort, then write the report in the format of `$SKILL_DIR/references/report-format.md`. If nothing survives, say so: an empty review is a valid result.

**Post to the PR.** When `scope.pr` names an open PR, and the user hasn't said not to post, post the confirmed findings as one review. It and each of its threads start with `[✈️ Preflight]`:

```bash
python3 "$SKILL_DIR/scripts/post_review.py" --repo <scope.github> --pr <n> --head <head> --findings <file.json>
```

- **Input:** the findings file holds the review summary and one entry per confirmed finding: fingerprint, path, line, optional startLine, and the finding in report format.
- **Placement:** lines inside the PR diff become inline threads. Other lines go in the review body under "Outside the diff". Nits go in the body, never as threads.
- **What it never does:** it never approves or blocks, never posts unverified or capped candidates, and never posts the same finding twice (each comment carries a fingerprint).
- **Dry run:** use `--dry-run` when the user asks for one.
- **Before the PR exists:** keep the report local. The first run after the PR is opened posts.
- Say in one line that the review was posted, with its link.

Save the state and the report as `state.md` describes. Save the state on every run, quick and empty reviews included: a hook (`scripts/pr_gate.py`) holds `gh pr create` in a gated profile's repos until the state's `lastReviewed` is the branch's latest commit. Then copy it into the ledger (Step 7): `python3 "$SKILL_DIR/scripts/ledger.py" sync`.

## Step 6: Threads and learnings

**On every run against an open PR,** read all its review threads: `python3 "$SKILL_DIR/scripts/threads.py" list --repo <scope.github> --pr <n>`. That covers ours (`ours: true`) and every other reviewer's.

- **Our open threads.**
  - If head fixes the finding, reply `✅ Addressed in <short sha>` and resolve it: `threads.py resolve --thread <id> --reply "…"`. This is the only case where the skill resolves a thread.
  - If the author declined it, re-check once against the code. If they're right, reply with a one-line acknowledgment and mark it `dismissed` in the state file. If the evidence still holds, reply once with what it shows. Either way, leave the thread open, replying with `threads.py reply` (it never resolves): a declined thread stays open, so the repo owner decides.
  - Post every reply through `threads.py`, which starts it with `[✈️ Preflight]` as everything the skill posts does. Never reply with `gh` directly.
- **Other reviewers' threads** (CodeRabbit, Gemini, cubic, Bugbot, people). Never resolve them; that is `resolve-pr-comments`' job. But read the author's replies: a decline with evidence of a kind of finding that will come back is a learning.

**Learnings.** When a finding is declined with evidence and would come back (from any reviewer, in a thread, or by the user in chat):
1. Propose one "Never flag" line for the repo's `REVIEW.md`: path glob, what not to flag, why, the date and the PR. Name its exception if it has one: a decline of an exotic case is not a decline of the whole class.
2. Show the line, and add it to `REVIEW.md` in the current branch on a yes, so it lands with the PR.
3. Every reviewer can read that file: this skill in Step 4, and CodeRabbit, where the repo uses it, through `knowledge_base.code_guidelines.filePatterns` in the repo's `.coderabbit.yaml` (its docs don't list `REVIEW.md` among the defaults). Check first whether the rule belongs in the repo's AGENTS.md or CLAUDE.md instead: anything an author needs before writing the code goes there.

## Step 7: Learn from outcomes

The ledger (`scripts/ledger.py`, kept at `~/.claude/preflight/ledger.json`) is how this skill gets better. It records what each review posted, and, once the PR is merged or closed, what happened to each finding, plus what other reviewers caught that the author fixed.

- **Every run:** `ledger.py sync` after saving the state (Step 5).
- **When the user asks how the reviews are doing, or every 20 settled PRs:** run `ledger.py sync`, `ledger.py settle` (reads PR threads through `gh`, read-only), then `ledger.py report`. The report gives:
  - the fix rate by skill version, finder and severity;
  - the misses: other reviewers' findings the author fixed, nowhere near one of ours, marked when a check refuted a candidate at that spot;
  - our declined findings.
- **A team's shared results.** When the profile sets `"sharedResults": true`, its folder is a clone of the team's profile repo. `sync` and `settle` then also write this reviewer's runs to `results/<login>/` there and push them (`scripts/shared.py`). `report`, run in one of the profile's repos, pulls and covers everyone's runs, with a By reviewer table; `--mine` reports this machine alone. Say so in one line when `sync` reports a push that failed: the commit waits for the next sync.
- **Act on it, then record the change.** Never edit this skill where it is installed (`$SKILL_DIR`, under `~/.claude/plugins/`): the next plugin update replaces it, and the change is lost. A change goes where it lasts:
  - A miss that recurs and is particular to this project becomes a check in the profile's `checks.md`, in `~/.claude/preflight/profiles/<name>/`. With no profile, it is a rule for the repo's AGENTS.md or CLAUDE.md, or a CI check.
  - A decline that recurs becomes a "Never flag" line in the repo's `REVIEW.md` (Step 6), or in the profile's `never-flag.md`.
  - A miss any repo could have, a finder whose findings are rarely fixed, or a check that wrongly refutes the same kind of finding is a change to Preflight itself. Write it up as a proposed edit to the plugin's source, `plugins/monogram/skills/preflight/` in https://github.com/monogram-labs/claude-plugins: the file, the old text, the new text, and the ledger numbers behind it. Show it to the user; they open the issue or PR, and a release bumps `VERSION`.
  - Show every proposed change before making it, and make a profile or repo change only on a yes. When the profile is a shared repo, the change goes in as a pull request there, so the team accepts or rejects it.
  - Then `ledger.py note "<what changed and why>"`, so the next report can compare before and after.
- **Mechanical misses go to CI, not to a lens.** A placeholder left in a changelog or an export nothing imports is cheaper and surer as a check in the repo's CI. Propose it in that repo instead.
- One review's numbers are noise: in testing, the same setup swung 10 points between runs. Decide from the ledger's totals, never from one PR.

