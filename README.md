# agent-rules

A public, work-free operating manual for running coding agents (Claude Code, Codex CLI,
OpenCode, and similar) — dogfooded configs, rules, and workflows kept in sync across machines.

It works as a **config hub**: `core.md` holds the shared, tool-agnostic rules; `map` says
where each tool reads its global instructions; `setup/install.sh` symlinks each installed
tool's load-point back at the hub. Edit the hub once, every agent gets it. A new machine is
`git clone` + `./setup/install.sh`. Start at `AGENTS.md`, then `docs/setup.md`.

## What's here

| path | what |
|---|---|
| `core.md` | the shared base rules every agent tool loads |
| `map` / `workflow-map` / `prompt-map` | tool → load-point → hub-file; workflow → skill catalogs; prompt template → runtime prompt dir |
| `AGENTS.md` | repo-local rules for working in this checkout (`CLAUDE.md` symlinks to it) |
| `check-privacy.sh` | pre-commit privacy guard; identity patterns live outside the repo |
| `docs/` | the manual: setup, memory & recall, compaction, model & quota, drift, custom providers |
| `rules/` | composable rule snippets |
| `workflows/` | own generic skills (`council`, `drain-memory`, `handoff`, `wrap`, `your-voice`) |
| `setup/` | `install.sh`, `doctor.sh`, example configs (macOS/zsh) |
| `tools/recall/` | a semantic memory-recall CLI (`recall.py` engine + `launcher.py`); shareable across machines via a reader/writer snapshot |

## Quick start

Clone into a dot folder (e.g. `~/.agent-rules`), not a project folder — every tool's global
load-point points back at this checkout.

```sh
git clone git@github.com:Jetemple/agent-rules.git ~/.agent-rules   # or HTTPS
cd ~/.agent-rules
# read docs/setup.md first — prereqs (Homebrew, Python 3.13, llama.cpp) and the order
./setup/install.sh --dry-run    # preview
./setup/install.sh              # create symlinks
./setup/doctor.sh               # verify
```

The installer also registers every skill declared in `workflow-map` by linking it into each
listed catalog (`agents`, `codex`, `claude`). For machine-private skills or source overrides,
create `~/.config/agent-rules/workflow-map` (same three-column format) — a private entry with
the same name replaces the public one:

```text
wrap ~/.private/wrap agents,codex,claude
```

Runtime-specific slash-command prompt templates (Pi's `/goal`, for now) are registered in
`prompt-map` and linked as `<name>.md` into the runtime's prompt directory
(`pi` → `~/.pi/agent/prompts`). They stay separate from `workflow-map` because their
invocation and interpolation syntax is runtime-specific. A pre-existing real file that is
byte-identical to the repo copy is adopted (replaced by the link); a differing one is left
alone and reported.

## Dependencies (not republished here)

- **Superpowers** — a separate skills marketplace; several workflows here assume it is
  installed. This repo links it as a dependency, doesn't republish its skills.
- **`embeddinggemma-300M` (GGUF)** — the embedding model `tools/recall` uses, served by
  llama.cpp (`llama serve`). Pull it per step 3 of `docs/setup.md`.

## Platform

macOS / zsh. Windows is not supported yet.

## License

MIT — see `LICENSE`.
