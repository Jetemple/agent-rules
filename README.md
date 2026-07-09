# agent-rules

A public, work-free operating manual for running coding agents (Claude Code, Codex CLI, and
similar) — dogfooded configs, rules, and workflows I keep in sync across my machines.

It is structured so an LLM on a fresh macOS machine can read it, inspect the machine, reproduce
this setup, and verify it took. Start at `AGENTS.md`, then follow `docs/setup.md`.

## What's here

- `AGENTS.md` — canonical operating rules both agents load (`CLAUDE.md` symlinks to it).
- `docs/` — the manual: setup, memory & recall, compaction, model & quota, drift.
- `rules/` — composable rule snippets.
- `workflows/` — my own generic skills (`handoff`, `wrap`, `your-voice`).
- `setup/` — `install.sh`, `doctor.sh`, and example configs (macOS/zsh).
- `tools/recall/` — a semantic memory-recall CLI.

## Quick start

```sh
# SSH, or HTTPS: git clone https://github.com/Jetemple/agent-rules.git
git clone git@github.com:Jetemple/agent-rules.git
cd agent-rules
# read docs/setup.md first — it lists prereqs (Homebrew, Python 3.13, Ollama) and the order
./setup/install.sh --dry-run    # preview
./setup/install.sh              # create symlinks
./setup/doctor.sh               # verify
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
