# Agent Operating Rules

Canonical rules both Claude Code and Codex load. `CLAUDE.md` is a symlink to this file.
Keep this lean — it loads by default. Load the linked docs only when the task needs them.

## Always-On Rules

- **Confirm before any remote mutation.** Before `git commit`, `git push`, merge, PR
  create/update, or any remote write, stop and get explicit confirmation after the repo,
  branch, action, and intended diff are known. Do not infer confirmation from a broad
  "fix it" / "go ahead" / "ship it".
- **No AI attribution anywhere.** No "Generated with" footers, no `Co-Authored-By` trailers,
  no AI/tool tokens in commits, branches, PRs, or docs.
- **Bounded tools first.** Prefer scoped local commands and narrow file reads over broad
  REST/API calls, full diffs, or whole-file dumps. See `rules/bounded-tool-use.md`.
- **Don't revert changes you didn't make.** Work with a dirty worktree unless asked to revert.
- **Use `rg` before slower/broader search.**

## Load Docs On Demand

| Task | Load |
|---|---|
| First-time machine setup, prereqs, install order | `docs/setup.md` |
| Memory + semantic recall | `docs/memory-and-recall.md` |
| Enabling auto-compaction on Claude & Codex | `docs/compaction.md` |
| Choosing a model / understanding plan vs pay-per-token cost | `docs/model-and-quota.md` |
| Canonical-file model, symlink scheme, syncing across machines | `docs/drift.md` |

## Composable Rules

Snippets in `rules/` compose into project-level rules files:
`git-safety.md`, `no-attribution.md`, `bounded-tool-use.md`.

## Workflows (skills)

Own generic skills live in `workflows/`. Third-party skills (e.g. the Superpowers
marketplace) are dependencies you install separately — this repo links them, never
republishes them. See README.

