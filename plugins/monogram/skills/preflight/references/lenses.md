# Lenses

Each lens is a list of checks a finder runs on the diff. They come from review-bot findings that authors accepted on real PRs, grouped by the check that would have caught them, and from a benchmark's misses. They apply to every repo. A project's own checks come from its profile (lens L5).

Every check ends the same way: if it finds something, name the trigger and the consequence, and point at the evidence. A check that finds nothing reports nothing.

## L1: Runtime behaviour

1. **Twins.** For each changed function, find the paths that must behave the same and compare them. Examples: list vs detail, a count vs the feed it counts, client check vs server check, one channel vs another (chat, SMS, email). Across repos: a parser ported between two services, an MCP tool vs its REST route, and a scaffold template vs the examples built from it.
   - **A new path beside existing ones** (a channel, a view, an editor, a route, a tool): list what each existing one does, such as its logging, guards, permission checks and id handling, and check that the new one does each. On real PRs, a new eval channel skipped its siblings' session logger, their escalation tool and their session-id format.
   - **A new rule** (a lock, a guard, a limit, a permission): find every path that writes or describes the same data, and check that the rule holds on each. That includes every view of one record (a form and its JSON view), an input left unchanged, and tool descriptions that say who may call. On real PRs, an id lock added to one editor view was missing from two others.
2. **Five outcomes of every await.** For each new `await`, check what happens when it is:
   - **superseded:** drop the stale response by scope;
   - **failed:** clear busy flags on rejection, and cache nothing;
   - **cancelled:** never clear the flag of the request that replaced it;
   - **poisoned:** a failure cached as an empty result, or a retry budget that never resets;
   - **unknown:** a non-idempotent call that failed in transit. Mark the outcome unknown and re-read, and release an idempotency reservation only on a definite refusal.
   - **Fill in the table, don't skim the list.** For each new `await` or server-action call in UI code, a hook or a handler, write one row: the call site, then for superseded, failed and cancelled the line that handles it, or "none". Every "none" a real caller can reach is a candidate. Return the rows under `coverage` (finder.md). Superseded includes the reader moving to another org, agent or record while the call runs: its result must not land in the new one. A server action called inside `startTransition` or an event handler with no `catch` is a failed row with "none". From 2026-10-30 to 11-21, 8 misses in four repos were rows of this table: a result written into the next agent's list, live rows dropped when the first read finished, a rejection nobody caught.
3. **State ownership.** Name each piece of state and its owner (org, core, case, session, thread, file, build, page), and check that it resets when the owner changes.
   - A framework that keeps a subtree mounted across navigation (the Next.js App Router does) resets nothing on its own. Key the subtree on the full scope, distinct from sibling keys.
   - A registry keys on the stable scope id, never on a per-connection one.
4. **Lifecycle.** Check what close, unmount, hangup, barge-in and end-of-call do to queued work, timers, buffers and in-flight requests. Timers are cleared and cannot start after close. A callback arriving mid-setup finds the state it needs.
5. **Check-then-act.** It must be one conditional write or run under a lock. Act on the row the guard read (by id), and gate dependent writes on the row count.
6. **Mutation blast radius.** A change to data also changes counts, previews, child rows, tallies and cached pages. Return confirmed IDs, and revalidate on partial success too.
   - Row-level security refuses a forbidden write by matching zero rows, with no error: count what changed.
7. **Edge values.** Use only inputs a real caller can send:
   - empty input, the cap and one past it, non-ASCII text (bytes vs `.length`);
   - `NaN`, `Infinity`, decimals, `__proto__`, repeated query keys (`string[]`);
   - step order: filter before slice, and every input in a hash;
   - traps: `slice(-0)`, `$&` in `replace`, PostgREST `max-rows`, NULL ordering, `ORDER BY` ties.
   - Check library behaviour in the installed source in `node_modules`. If only a run would settle it, report it as suspected; its verifier runs the probe.
8. **Error and timeout paths.** No `catch` swallows errors it wasn't written for, and cleanup doesn't hide the original error. Cancellation propagates. Outbound work has a deadline and a retry limit.
   - **Ignored errors.** A result shaped `{ data, error }` (Supabase, PostgREST, many SDKs) checks `error` before it uses `data`, and before a fallback that would hide it (a default time zone, an empty list). A failed read is not "no rows".
   - **Missing values.** For each new read of something that can be absent, name what happens when it is: a header, an env var, a CLI argument, a callback's argument, an optional row, a lookup by a key that came from input (`CONFIGS[arg]`, `map.get(id)`). It fails loudly with a clear message, or takes a stated default. It never reaches a property access on `undefined` or a silent `"undefined"` in a URL. From 2026-10-30 to 11-21, 8 misses in five repos were this, in API, CLI and UI code alike.
9. **UI states.**
   - States: empty account, loading, failed lookup, null, zero items, narrow width. Each shows a true sentence and a way forward.
   - Interaction: rows work by keyboard, nothing is tooltip-only, focus moves into what opens, reduced motion is respected.
   - Keys: Enter in a text field never starts a costly or irreversible action (a payment, a send, a delete) unless that is the form's only button. Enter and other key handlers ignore IME composition (`event.nativeEvent.isComposing`). A key that removes something (Backspace on a chip) goes through the same guard as the click.
   - Pending work: while a save or delete is in flight, every way out (Cancel, Escape, a click outside, back, closing the sheet) is disabled or still lands the result safely, and a second submit can't start. **Fill in the table:** for each new dialog, sheet or form with an async action, write one row per way out, naming what it does while the action runs. Return the rows under `coverage`. This was missed 3 times before the check was added as a one-line rule, and 5 more times in two repos after.

## L2: Contracts and integration

General reviewers miss this most. In testing, two general review skills caught 1 of 5 integration findings, and docs, specs and changelogs a change made false were a third of all accepted findings. For a project with a profile, read the sibling repos' main branch (`repos.md`).

1. **Copies of a changed fact.** For every name, number, route, default, limit, version or behaviour the diff changes, `rg` this repo and the siblings, and flag each copy that is now false. Look in the same page, specs, READMEs, AGENTS.md, comments, SQL `COMMENT ON`, docs MDX, setup prompts, `.rest` examples, MCP tool descriptions and synced skills.
2. **Claims vs code.** Open the code behind each sentence the diff adds or edits, in docs, specs, READMEs and CHANGELOGs alike.
   - Find the exception to each absolute ("always", "never", "every", "once", "guaranteed").
   - A timeout, a wait or a retry limit is a bound, not a guarantee: flag a sentence that says something is sure to happen within it.
   - Give a version-dependent claim its version boundary.
   - Every example (a code block, a JSON body, sample values, a fallback) gives the result the code gives for it. Trace it through the code.
   - A required order of steps (migration, then API, then console) is stated wherever a reader acts on it: migration notes, release notes, upgrade steps. Flag a place that leaves it out or says otherwise.
   - Docs' shell commands must run as written. Report one you doubt; its verifier runs it.
   - From 2026-10-30 to 11-21, 9 misses in six repos were docs that promised more than the code: a guarantee after a failure, a wrong example, a missing rollout order, a runbook that said entries stay masked when the code unmasks them.
3. **Rules that contradict each other.**
   - List every rule the change adds or edits: "never", "always", "must", "only", a refusal, a default.
   - Check each against every other rule in the same doc and in the specs it links. Example: a sentence that says something never happens, beside a rule that makes it happen.
   - Also check stale Status, "Remaining" and amendment counts, lagging indexes (specs/README, AGENTS.md ranges), dates after the change, and broken cross-references.
   - An ADR changes by a dated amendment or a new ADR that supersedes it. Flag only a silent rewrite.
4. **API and MCP parity.**
   - Every advertised parameter reaches the query, and descriptions name the column actually filtered.
   - Send an explicit `false` when the default is `true`.
   - Request examples (`.rest`, `.http`, curl in docs) match their fixtures.
5. **Values across layers.**
   - Follow each new field, flag, channel name or ID through every allowlist, proxy, schema, serializer and lookup, and flag a value accepted at one layer and dropped at the next.
   - Flag a value normalized in one place (lower-cased, trimmed, aliased) and used raw in another. Example: a channel stored lower-case but looked up verbatim.
6. **Identifiers and keys.**
   - React keys are unique among siblings.
   - A composite key built by joining strings is collision-free. `${model}:${voice}` collides with a model named `x:y`, so use a separator the parts can't contain, or a structured key.
   - Slug ≠ UUID. Case-normalized joins. A fallback key is never exposed as an id.
7. **External API limits.** A value sent to a provider (an LLM API, a payments or messaging API, a hosted database) must fit the type and range the provider declares: int32 fields, enums, lengths, rounding. Example: a duration forwarded with only a `typeof number` check, where Gemini wants an int32.
8. **Versions.**
   - When an upstream fix lands, raise the minimum everywhere: package.json files, the scaffold template, the lockfile.
   - Packaged code never builds paths from its source location (`import.meta.dir`, `__dirname`): they break once it is bundled or installed.
9. **Release placeholders.** A placeholder for a release not yet published (`PLACEHOLDER`, an unpublished version) with nothing that stops it from shipping. The finding is the missing guard, a test or build check that fails while it remains.
10. **Duplicated contracts.** A new string, label set, route sentinel or markup block that already exists elsewhere comes from one shared source.

## L3: Data and tests

1. **Migrations and data integrity:**
   - UPDATE policies are limited to editable columns, and write policies bind a row to its tenant.
   - Triggers cover explicit values, `service_role` and self-reference.
   - Index the foreign key you started filtering on.
   - Constraint swaps are replay-safe, and an applied migration is never edited.
   - Checked-in schema dumps and generated database types are regenerated from the database, never hand-edited. The scanner flags some of this; verify it.
2. **Tests that cannot fail.** Name the regression each new assertion catches, and reason through whether it would fail without the change. Report one you doubt as suspected; its verifier mutates a scratch copy (`git archive <head> | tar -x -C /tmp/preflight-probes/<name>`) and runs the test there.
   - Mocks honour their arguments. Fixtures reach the branch (slug ≠ UUID, no tied sort keys).
   - Build a fresh `Response` per call.
   - No negative assertion inside `waitFor`, no loops that run zero times, and no expected value that equals the CI default.
3. **Missing failure-path tests.** Every new `catch`, `{ success: false }` return or format branch has a test that drives it.

## L4: Design contracts (spec mode, or when a change adds a contract)

For each new contract, flag what is left undefined:
- the order of concurrent writes, and what wins;
- what a reader does with a missing or unknown version;
- the canonical bytes before hashing or truncating;
- limits and quotas;
- state kept in one process's memory (sessions, rate limits, caches) when the service runs more than one instance or restarts;
- the success response of each route it adds, not only its errors;
- who may change an endpoint or identity;
- PII retention;
- recovery of a multi-step call that costs money (buying a phone number, a billed provider call);
- what the UI and API say while the state is pending, failed or partial.

Read the spec's ADRs, the schema and the code it names first. It may already be defined there.

## L5: Project checks

What this project enforces that a general reviewer would not know: the context file's "Project checks" section, from the project's profile. Every finder runs them. A repo with no profile has none beyond its own rules files, which lens L9 walks.

## L6: Security

Run in depth when `signals.security`, `signals.data`, `ci` or `dependencies` is non-empty. A security finding needs an **exploit path**:
- who the attacker is: an anonymous user, a member of another org, the agent's own model, a PR author;
- what they control;
- each step from the entry point to the sink;
- the impact.

Without a path it is at most a Minor note. Authenticated paths are **not** exempt: a cross-org read or write by a signed-in member is the most important class here.

1. **Entry points and authorization.** List every new or changed entry point: route, Server Action, API endpoint, MCP tool, webhook, RPC, CLI command. For each, check:
   - authentication, then authorization (role, org membership), before any side effect;
   - every query scoped to the org: RLS for user clients, an explicit `organization_id` for service-role clients;
   - IDs from the client or the model are never identity;
   - an IDOR by guessing another org's slug or UUID fails.
   - A route exempted from the auth middleware authenticates in its own handler.
2. **RLS and grants.**
   - New tables have RLS, and policies for each operation they need.
   - UPDATE policies can't re-parent a row.
   - `SECURITY DEFINER`: `search_path` pinned, `EXECUTE` revoked from PUBLIC, anon and authenticated, row count asserted.
   - Views are `security_invoker` where intended.
   - Grants on new tables follow the project's default privileges, which differ between projects. Read the earlier migrations, or the default privileges in a schema dump, to see which applies. Where new tables start with ALL granted to anon and authenticated, revoke what isn't needed: a narrow GRANT narrows nothing. Where they start with none, grant what the Data API needs, or every client query on the table fails.
3. **Injection and encoding.** Check SQL or PostgREST filter strings built from input (`.or()`, `rpc` with dynamic SQL), shell commands, generated code, and HTML (`dangerouslySetInnerHTML`, rendered Markdown). Also:
   - CSV formulas, header CRLF, open redirects, path traversal;
   - prototype pollution through user-chosen map keys: use `Object.create(null)` or `Object.hasOwn`.
4. **SSRF and outbound calls.**
   - Validate the destination on every hop, redirects included, with the repo's URL guard if it has one.
   - Timeout, byte cap, and a reader cancel on every call.
   - No secret sent to an unguarded destination.
   - Webhooks verify their signature against the exact URL the provider signed, and replay is considered.
5. **Secrets and PII.**
   - Nothing secret in client bundles (`NEXT_PUBLIC_*`, server-only imports), logs, error bodies, URLs or query strings.
   - Tokens are compared with `timingSafeEqual` on equal-length buffers.
   - PII is masked in logs and kept only as long as the spec says.
6. **Cost and abuse.**
   - Rate limits on partner and cost surfaces (SMS and email sends, LLM calls).
   - Idempotency reserved before a billed side effect.
   - No unbounded loop or retry that bills.
   - An endpoint that spends money refuses to run without its secret.
7. **Dependencies and CI.**
   - New packages: typosquats, install scripts, unmaintained.
   - Audit advisories reachable from the changed code (the scanner runs `bun audit` in bun repos; elsewhere, run the package manager's audit).
   - Workflows: `pull_request_target`, expression injection, broad `permissions`, secrets in logs.
   - Verify scanner hits here.

## L7: Performance (hot paths only)

First name how often the path runs: per request, per turn, per audio frame or per render, as against per deploy or per CLI run. Flag only hot paths, and give a realistic size, from the schema, a spec, or the data the code reads.

1. **Database.**
   - N+1 queries (a query inside a loop or `map`).
   - Unpaged reads of growing tables (PostgREST `max-rows` caps silently).
   - No index for a new filter, order or join column (check the schema).
   - `select('*')` of wide jsonb columns in list views.
   - Counts on large tables per render.
2. **Request, stream and turn paths.**
   - Sequential awaits that could run together, on the per-request or per-turn path only.
   - Blocking work before the first byte or the first audio.
   - Per-chunk allocations, and unbounded buffers or queues.
3. **React and Next.js.**
   - Effects with unstable dependencies that refetch in a loop.
   - Context values that change identity every render.
   - Waterfalls in Server Components (awaits that could be `Promise.all`).
   - Client modules pulling in heavy server-only libraries.
   - Very long lists rendered whole, when they can really get long.
4. **Network.** Unbounded fan-out, and retries without backoff.

## L8: Code quality (at most 3 candidates)

Report only what costs something later. Never above Minor unless a concrete failure follows.

1. **Duplicated logic the change introduces:** the same computation in two places that must stay in step. This is the seed of a future twin bug.
2. **Dead code the change leaves:** exports nothing imports, components nothing renders, fixtures no test reads. Remove what the change made unused.
3. **Abstraction with one caller,** or options nobody passes.
4. **A file the change pushes over a size cap the repo sets.**
5. **A name that will cause a wrong use,** not one that is merely not to taste.

Never: formatting, naming taste, settled conventions (function vs arrow, interface vs type), or "consider".

## L9: Repo standards

Adapted from the Standards axis of mattpocock/skills `code-review` (MIT, see `THIRD_PARTY.md`). In the benchmark, that axis found rules a change broke that no lens here listed: a decision the repo's log records with no entry, an export nothing imports.

1. **Read the rules first.** Read every file in this repo that says how work should be done: AGENTS.md or CLAUDE.md, CONTRIBUTING, other coding tools' rules (`.cursor/rules/`, `.cursorrules`, `.github/copilot-instructions.md`, GEMINI.md), coding-standards files, `docs/internal/`, design.md, and the repo's decision logs (ADRs, a decisions or MEMORY file). In a monorepo, also read the rules files in the folders the diff touches. Read them at base. The guidance paths in the context file's repo notes are the start, not the whole list.
2. **Walk each rule that applies to the changed paths** against the diff. Report a rule the change breaks, quoting the file and the rule. Skip what a linter or test in this repo already enforces, the "Settled conventions", and anything a "Never flag" entry covers.
3. **Records the repo keeps.** When the change makes the kind of decision a record here already logs (a dependency policy, a reversal of an ADR, a changed default), check that the record got its entry, and that an entry the change reverses is amended or superseded.
4. **Code the change adds that nothing uses:** an export nothing imports, a parameter no caller passes, a branch no caller reaches. Search this repo and the siblings' main before you claim it.
5. **Docs prose.** In the prose the change adds or edits in docs readers see (a docs site, a README, a CHANGELOG, a spec), report:
   - a broken sentence: a doubled word or conjunction ("or a …, or an an …"), a list whose items don't share one shape, a sentence that says the opposite of what it means;
   - a break of a prose rule the repo writes down (its AGENTS.md, a style guide, the profile's checks): quote the rule.
   
   Never report a rule that isn't written down, however common it is elsewhere. Severity Trivial, unless the sentence misleads a reader about behaviour (then L2.2). One candidate per paragraph. Before this item, only a reviewer outside Preflight caught these.

A rule here is a standard to enforce, not a taste. Never report a code smell by name ("Feature Envy", "Primitive Obsession"): in the benchmark those judgement calls made up most of the false findings.

## L10: The change's own claims

Adapted from the Spec axis of mattpocock/skills `code-review` (MIT, see `THIRD_PARTY.md`). That axis caught changesets and docs that described a change wrongly.

1. **List what the change says about itself:** the commit messages, the PR title and body, the changeset or CHANGELOG entry, the migration notes, and the spec or issue it names. Quote each claim.
2. **Check each claim against the code at head.**
   - A claim that is false or wider than the code: "only used by", "installs without changes", "type-checks only when", "no migration".
   - Something the change says it does that it does not do, or does only in part.
   - A requirement in the named spec that is missing or partial.
3. **What the code does that no claim mentions,** when a reader of the changeset or the PR needs to know it: a behaviour change, a new requirement on the consumer, an install that now breaks, a doc the consumer must re-sync.
4. **The label against the change.** A version bump, a FIX or BREAKING label, or a "patch" that does not match what the change's own notes describe.

L2 covers copies of a changed fact elsewhere, and sentences added to shared docs. This lens is about the change's description of itself. Overlap is fine: triage merges.
