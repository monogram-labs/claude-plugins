# Monogram Labs Claude Code plugins

A plugin marketplace for Monogram Labs. It holds one plugin, **monogram**, which brings **Code Preflight** (Preflight for short): a pre-push and pre-merge code review that checks every finding against the code before reporting it.

## Install

In Claude Code:

```
/plugin marketplace add monogram-labs/claude-plugins
/plugin install monogram@monogram-labs
```

Or from a terminal: `claude plugin marketplace add monogram-labs/claude-plugins`, then `claude plugin install monogram@monogram-labs`. Restart Claude Code afterwards.

To update later, run `claude plugin marketplace update monogram-labs` and then `claude plugin update monogram@monogram-labs`.

The plugin was called `elegant` until version 1.1.0. If you installed it under that name, run `claude plugin uninstall elegant@monogram-labs`, then `claude plugin marketplace update monogram-labs` and the install command above.

## What you need on your machine

- Claude Code, `git`, `python3` (standard library only), and `gh` logged in to GitHub.
- `bun`, for the probe checks in JavaScript and TypeScript repos.
- Optional, for stronger scans: `brew install gitleaks actionlint zizmor shellcheck`.
- For a project with a profile: the profile in `~/.claude/preflight/profiles/<name>/`, and the project's repos cloned side by side in one folder, so the review can compare across them. A team keeps its profiles in a private repo of its own and clones it there.

A full review takes about 15 to 20 minutes and uses about 2 to 3 million tokens. See [plugins/monogram/README.md](plugins/monogram/README.md) for how to use it.

## License

MIT. See [LICENSE](LICENSE). Bundled third-party material keeps its own MIT notice in `plugins/monogram/skills/preflight/THIRD_PARTY.md`.
