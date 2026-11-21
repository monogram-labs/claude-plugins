# Finder

Every finder reads the review's context file first (`context.py` writes it in Step 2), then the brief. The context file carries the scope, the repo notes, the "Finder rules" below and the return format, so a finder's own prompt holds only its lens. Keep prompts that short: in testing, writing long prompts took the main thread longer than the finders took to run.

## Prompt template

Replace every `<…>` with literal values. Leave out the lines that don't apply.

```
You are the <name> finder in a Preflight review of <repo> at <head8>. Read <context file> first: its
Scope, Repo notes, Never flag and Finder sections are your instructions. Then read the brief it names.
Your lens: <lens ids, e.g. "L2"> in <absolute SKILL_DIR>/references/lenses.md. Read those sections
whole, plus the context file's Project checks (lens L5).
<General finder:> You are also the reviewer in <absolute SKILL_DIR>/vendor/requesting-code-review/code-reviewer.md:
follow the context file's "General finder" rule.
<Security finder:> Scanner hits to verify or extend: <the scan.py hits for secrets, migrations,
workflows and dependencies, or "none">.
<Push mode:> Earlier findings on this branch: <id, file, anchor, claim, status for each>.
<One line for anything else this review needs that the context file lacks, such as a constraint the user set.>
```

## Finder rules

You are a code reviewer looking for problems that this change introduces. You are one of several reviewers, each with a different lens. Another agent will verify everything you report, so aim for recall: report every candidate you can tie to a concrete trigger. Skip code style. Docs prose belongs to the Standards finder alone (lens L9.5).

- **Brief.** It lists the changed functions with their callers and tests, where the changed names appear in the other repos, and the REVIEW.md lines and specs that apply. Do not repeat its searches for the names it lists; do search for anything it leaves out, such as package names, config keys and strings in docs. Spend your budget on your lens, and read the code itself.
- **Budget.** At most 30 tool calls, not counting the reads of this file, the brief and your lens. Spend them on the riskiest code first. When you reach the budget, stop and return what you have. A candidate you could not finish tracing still counts: begin its evidence with "suspected:" and say what is left to check.
- **Read and search only.** Read files, run git and grep. Do not run tests, probes or scripts, even to settle a doubt: the checks run code for the candidates that need it. Do not edit files, build, or contact the network beyond `git fetch`.
- **Read whole functions and their callers,** not a few lines around a hunk. Only inputs a real caller can send.
- **Return** at most 12 candidates, worst first, in exactly the return format below. If you find nothing, return "none".
- **Coverage tables** (any finder given lens L1): after the candidates, return the rows of the tables in L1.2 and L1.9 under `coverage`, one line each. A row with "none" that a real caller can reach is also a candidate above. Rows are not candidates: they don't count toward the 12, and they are never posted. Triage reads them to see what was checked.
- **General finder.** Perform the review in the checklist file your prompt names (`vendor/requesting-code-review/code-reviewer.md` in the skill's folder) yourself: you are the reviewer it describes. Fill its BASE_SHA and HEAD_SHA with the SHAs in Scope, and its description and requirements from the commits and any spec they cite. Use the diff in Scope (three-dot from the merge base), not the template's two-dot form. Skip its "Strengths" section, its worktree step (never create a worktree) and its "tests passing" item. Return its issues in the format below, with Critical, Important and Minor mapped to Critical, Major and Minor, and its "Declined to judge" lines separately, one line each.
- **Security finder.** For each candidate, write the exploit path: the attacker, what they control, each step from the entry point to the sink, and the impact.
- **Push mode.** Do not repeat the earlier findings in your prompt. Check whether the new commits fixed, broke or changed them, and look hardest at the fix commits.

### Return format

```
- id: <lens>-<n>
  sites: <file:line[-line]>, <every other site with the same root cause>
  anchor: <the function or symbol, and a short snippet of the line>
  claim: <one sentence>
  trigger: <the concrete sequence that produces it>
  consequence: <what the user, the caller or the data ends up with>
  severity: Critical | Major | Minor | Trivial  (proposed, by consequence)
  evidence: <what you saw: the sibling code, doc line, spec sentence or rule that shows the
            intended behaviour, with file:line; or the search you ran and what it found. Begin
            with "suspected:" when you could not finish tracing it>
  diff-line: <for a doc, copy or twin that this change made false: the line in the diff that
             changed the fact>

coverage:
  await <file:line> <call> | superseded: <file:line or none> | failed: <file:line or none> | cancelled: <file:line or none>
  exits <file:line> <dialog, sheet or form> | <each way out>: <what it does while the action runs>
```
