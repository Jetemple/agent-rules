# agent-rules

A public, work-free operating manual for running coding agents (Claude Code, Codex CLI,
OpenCode, and similar) — dogfooded configs, rules, and workflows I keep in sync across my
machines.

It works as a **config hub**: `core.md` holds the shared, tool-agnostic rules; `map` says
where each tool reads its global instructions; `setup/install.sh` symlinks each installed
tool's load-point back at the hub. Edit the hub once, every agent gets it. A new machine is
`git clone` + `./setup/install.sh`. It is structured so an LLM on a fresh macOS machine can
read it, inspect the machine, reproduce this setup, and verify it took. Start at `AGENTS.md`,
then follow `docs/setup.md`.

## What's here

- `core.md` — the shared base rules every agent tool loads.
- `map` — tool → load-point → hub-file; the director `install.sh` reads.
- `workflow-map` — workflow name → source → skill catalogs; the public skill registry.
- `AGENTS.md` — repo-local rules for agents working in this checkout (`CLAUDE.md` symlinks to it).
- `check-privacy.sh` — pre-commit privacy guard; your identity patterns live outside the repo
  in `~/.config/agent-rules/private-patterns`, so the guard itself stays generic.
- `docs/` — the manual: setup, memory & recall, compaction, model & quota, drift.
- `rules/` — composable rule snippets.
- `workflows/` — my own generic skills (`drain-memory`, `handoff`, `wrap`, `your-voice`).
- `setup/` — `install.sh`, `doctor.sh`, and example configs (macOS/zsh).
- `tools/recall/` — a semantic memory-recall CLI.

## Quick start

Clone it into a dot folder in your home directory (e.g. `~/.agent-rules`), not a project or
code folder — it's a config hub every tool's global load-point points back at, not a project
you `cd` into day to day.

```sh
# SSH, or HTTPS: git clone https://github.com/Jetemple/agent-rules.git
git clone git@github.com:Jetemple/agent-rules.git ~/.agent-rules
cd ~/.agent-rules
# read docs/setup.md first — it lists prereqs (Homebrew, Python 3.13, Ollama) and the order
./setup/install.sh --dry-run    # preview
./setup/install.sh              # create symlinks
./setup/doctor.sh               # verify
```

The installer also registers every skill declared in `workflow-map` by linking it into each
listed catalog (`agents`, `codex`, or `claude`). The checked-in map is the public registry. For
machine-private skills or source overrides, create
`~/.config/agent-rules/workflow-map` (or `$XDG_CONFIG_HOME/agent-rules/workflow-map`) with the
same three-column format. A private entry with the same name replaces the public entry:

```text
wrap ~/.private/wrap agents,codex,claude
```

## Dependencies (not republished here)

- **Superpowers** — a separate skills marketplace. Several workflows here assume it is
  installed; this repo links it as a dependency and does not republish its skills. Install it
  from its own source.
- **`embeddinggemma:300m`** — the Ollama embedding model `tools/recall` uses. Pull it per
  `docs/memory-and-recall.md`.

## Platform

macOS / zsh. Windows is not supported yet.

## License

MIT — see `LICENSE`.
