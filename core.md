# Core Agent Rules

The shared, tool-agnostic rules every agent loads. Kept lean — it loads by default in every
session. No personal data, no employer references: this file is public and synced across
machines. Tool-specific or personal detail lives in each tool's own file, not here.

## Always-on

- **Confirm before any remote mutation.** Before `git commit`, `git push`, merge, PR
  create/update, or any remote write, stop and get explicit confirmation once the repo, branch,
  action, and intended diff are all known. A broad "fix it" / "go ahead" / "ship it" is not
  approval for a specific commit or push.
- **No AI attribution anywhere.** No "Generated with" footers, no `Co-Authored-By` trailers, no
  AI/tool tokens in commits, branches, PRs, tags, or docs. Write as if the human authored it.
- **Bounded tools first.** Treat context as a budget. Prefer `rg` and narrow file reads over
  broad REST/API calls, full diffs, or whole-file dumps. Pipe broad commands through a filter so
  only the relevant slice reaches the session. When you don't know which file holds an answer,
  query the shipped semantic index (`tools/recall`) before grepping blindly. For large scouting
  or cross-file mapping, delegate to a bounded subagent with an explicit objective, scope, output
  contract, and stop condition.
- **Don't revert changes you didn't make.** Work with a dirty worktree unless asked to revert;
  foreign uncommitted changes are usually another agent's work in progress, not an anomaly.
- **State reality.** Report what's done AND verified, what's done-but-unverified, what's blocked,
  and what's an open decision. Don't imply more is finished than is.
- **Verify by running.** For anything user-facing (UI, behavior, a flow), produce evidence —
  run it, show the output — rather than claiming it works because it builds or reads correctly.

## Model & effort

- Start from the cheapest model/effort that can plausibly do the task well; escalate on evidence
  (a concrete failure, a named risk, high stakes), not as a habit.
- Cost is a tie-breaker only. When it ships, intelligence and taste beat cost.
- Bulk mechanical work (clear specs, migrations, data munging) → cheap/fast model. Anything
  user-facing (UI, copy, API design) → a model with good taste. Reviews benefit from a second,
  more capable model as an independent perspective.

## Environment (macOS / zsh)

- Shell is zsh (no automatic word-splitting) and macOS ships no GNU `timeout`. Pass multi-arg
  commands as arrays, not space-separated strings, and use your harness's own timeout rather
  than a `timeout` binary.
- A command that hangs is usually waiting on a keychain / credential prompt, not working.

## Composition

This is the shared base. Each tool reads it through its own instruction file (see `map`), and may
layer tool-specific or personal rules on top via that file. Personal detail never lands here —
`check-privacy.sh` enforces it.
