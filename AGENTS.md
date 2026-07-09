# Agent Operating Rules (this repo)

Rules for any agent working in THIS checkout. The shared, tool-agnostic rules every agent
loads globally live in `core.md` — the hub file that `map` + `setup/install.sh` project into
each tool. This file layers only the repo-local rules on top. (`CLAUDE.md` symlinks here.)

## This repo is public — non-negotiables

- **No personal data, ever.** No real names, personal emails, employer names, hardcoded home
  paths, phone numbers, or keys. `check-privacy.sh` runs as a pre-commit hook, but a denylist
  is not proof of safety — also review the diff for identity before any push.
- **Commit identity:** before committing, verify `git config user.name` / `user.email` are the
  public handle + noreply email set LOCALLY in this repo — never a real name or employer email.
- **Generic means generic.** Paths as `~` or `$HOME`, examples anonymized. A rule that only
  makes sense with personal context belongs in a private overlay, not here.

## Layout

- `core.md` — the shared base every agent tool loads. Edit rules there.
- `map` — tool → load-point → hub-file, the director. Add a tool = add a line.
- `check-privacy.sh` — privacy guard. Identity patterns live OUTSIDE the repo in
  `~/.config/agent-rules/private-patterns`, so the guard never encodes who you are.
- `setup/` — `install.sh` (wires the map + hook), `doctor.sh` (verifies), statusline, hooks.
- `docs/` — the manual: setup, memory & recall, compaction, model & quota, drift.
- `rules/` — composable rule snippets for project-level rules files.
- `workflows/` — generic skills (`handoff`, `wrap`, `your-voice`).
- `tools/recall/` — a semantic memory-recall CLI.

## Load Docs On Demand

| Task | Load |
|---|---|
| First-time machine setup, prereqs, install order | `docs/setup.md` |
| Memory + semantic recall | `docs/memory-and-recall.md` |
| Enabling auto-compaction on Claude & Codex | `docs/compaction.md` |
| Choosing a model / understanding plan vs pay-per-token cost | `docs/model-and-quota.md` |
| Hub model, symlink scheme, syncing across machines | `docs/drift.md` |

## Workflows (skills)

Own generic skills live in `workflows/`. Third-party skills (e.g. the Superpowers
marketplace) are dependencies you install separately — this repo links them, never
republishes them. See README.
