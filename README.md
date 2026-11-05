# agent-rules

A public, work-free operating manual for running coding agents (Claude Code, Codex CLI,
OpenCode, and similar) — dogfooded configs, rules, and workflows kept in sync across machines.

It works as a **config hub**: `core.md` holds the shared, tool-agnostic rules; `map` says
where each tool reads its global instructions; `setup/install.sh` wires each installed
tool's load-point back at the hub. Edit the hub once, every agent gets it. A new machine is
`git clone` + `./setup/install.sh`.

## What's here

| path | what |
|---|---|
| `core.md` | the shared base rules every agent tool loads |
| `map` / `workflow-map` / `prompt-map` | tool → load-point → hub-file; workflow → skill catalogs; prompt template → runtime prompt dir |
| `AGENTS.md` | repo-local rules for working in this checkout (`CLAUDE.md` symlinks to it) |
| `check-privacy.sh` | pre-commit privacy guard; identity patterns live outside the repo |
| `rules/` | composable rule snippets |
| `workflows/` | own generic skills (`council`, `drain-memory`, `handoff`, `wrap`, `your-voice`) |
| `setup/` | `install.sh`, `doctor.sh`, example configs (macOS/zsh) |
| `tools/recall/` | a semantic memory-recall CLI ([setup](tools/recall/README.md#setup)) |

## Quick start

Prerequisites: Homebrew and Python 3.13 (`brew install python@3.13`; 3.14 lacks a prebuilt
`libsql` wheel). `tools/recall` also needs llama.cpp; see its README.

Clone into a dot folder (e.g. `~/.agent-rules`), not a project folder — every tool's global
load-point points back at this checkout.

```sh
git clone git@github.com:Jetemple/agent-rules.git ~/.agent-rules   # or HTTPS
cd ~/.agent-rules
./setup/install.sh --dry-run    # preview
./setup/install.sh              # create links
./setup/doctor.sh               # verify
```

`install.sh` is idempotent and never overwrites a real (non-symlink) file. It:

1. Wires each *installed* tool's load-point from `map` (tools without a config dir are skipped).
2. Links every skill in `workflow-map` into each listed catalog (`agents`, `codex`, `claude`).
   Every registry is validated whole first; a bad row installs nothing.
3. Links runtime-specific prompt templates from `prompt-map` (Pi's `/goal`, for now) into the
   runtime's prompt dir (`pi` → `~/.pi/agent/prompts`). A byte-identical real file is adopted;
   a differing one is left alone and reported.
4. Creates a core-only `~/.claude/AGENTS.md` stub if absent and links `~/.claude/CLAUDE.md` to it.
5. Installs the privacy-guard pre-commit hook. An executable
   `~/.config/agent-rules/pre-commit-extra` may add private checks; it runs before, never
   instead of, the canonical guard.
6. Creates `~/.config/agent-rules/private-patterns` if absent. **Edit it:** add your name,
   handles, and employer as regexes so `check-privacy.sh` blocks them.

For machine-private skills or source overrides, create `~/.config/agent-rules/workflow-map`
(same three-column format). A private entry with the same name replaces the public one:

```text
wrap ~/.private/wrap agents,codex,claude
```

## How the hub wires each tool

Each `map` row is `tool  load-point  hub-file  mode`:

| mode | what install.sh writes | use when |
|---|---|---|
| `link` | a symlink straight at `core.md`; live on every edit | the tool needs the shared rules and nothing else |
| `block` | a real file with `core.md` inside a managed fence; your own rules live outside it | the tool can't import files but needs private rules too |

The fence:

```
# >>> agent-rules hub (managed by install.sh — do not edit) >>>
…core.md, verbatim…
# <<< agent-rules hub <<<
```

`block` isn't live: re-run `install.sh` after editing `core.md`. `doctor.sh` checksums the
fenced region and fails on drift. Converting `link` → `block` keeps a pre-existing file below
the fence; a file with mismatched markers is backed up to `.bak` first.

Codex is `block`: it doesn't expand `@import` lines and has no extra-instructions key. Claude
stays a private real file that pulls the hub in with one line
(`@/absolute/path/to/agent-rules/core.md`), because it expands imports and its global file
holds personal rules that don't belong in a public repo.

Secrets, the recall corpus and `memory.db`, and voice profiles are never tracked; they stay
on each machine.

## Compaction

`core.md` assumes auto-compaction is on. The 200k-token window below is a choice; size it to
the model you run.

Claude Code settings JSON (`setup/settings.example.json`):

```json
{
  "autoCompactEnabled": true,
  "env": {
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "100"
  }
}
```

The window is capped at the model's real context; `100` defers compaction as far as Claude's
safety buffers allow. `/context` shows the live trigger (the status line still measures the
full window). A running session may not pick up the change until restart.

Codex, in `~/.codex/config.toml`:

```toml
model_auto_compact_token_limit = 200000
```

## Dependencies (not republished here)

- **Superpowers** — a separate skills marketplace; several workflows here assume it is
  installed. This repo links it as a dependency, doesn't republish its skills.
- **`embeddinggemma-300M` (GGUF)** — the embedding model `tools/recall` uses, served by
  llama.cpp (`llama serve`). See [tools/recall/README.md](tools/recall/README.md#setup).

## Platform

macOS / zsh. Windows is not supported yet.

## License

MIT — see `LICENSE`.
