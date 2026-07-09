# Drift: canonical files, symlinks, and staying in sync

Multiple agents read multiple instruction files, and you run on more than one machine. Without
a scheme, the files **drift** — Claude Code reads one thing, Codex reads another, and your
laptop disagrees with your desktop. This is how to keep one source of truth.

## Canonical-file model

Claude Code's default instructions file is `CLAUDE.md`; Codex's is `AGENTS.md`. Neither reads
the other by default. So pick one canonical file and symlink the rest to it:

- **`AGENTS.md` is canonical** (the emerging cross-tool standard).
- **`CLAUDE.md` is a symlink → `AGENTS.md`.**

```sh
ln -s AGENTS.md CLAUDE.md
```

Now a single edit reaches every runtime. This applies at both scopes:

- **Global** — the hub model (below): each tool's global load-point symlinks at `core.md` in
  this repo.
- **Project** — the repo's `CLAUDE.md` → its `AGENTS.md`.

Repo files are inert until install creates the home-level symlinks. `setup/doctor.sh` verifies
both the global and project load paths resolve.

## The hub model (global scope)

This repo is the hub. Three pieces:

- **`core.md`** — the shared, tool-agnostic rules. The only file you edit to change behavior
  everywhere.
- **`map`** — one line per tool: `tool  load-point  hub-file`. The load-point is where that
  tool reads its global instructions (`~/.codex/AGENTS.md`, `~/.config/opencode/AGENTS.md`,
  `~/.gemini/GEMINI.md`, …).
- **`setup/install.sh`** — reads the map and symlinks each *installed* tool's load-point back
  at the hub file. Skips tools whose config dir doesn't exist; refuses to clobber a real file.

Claude Code is the one special case: its global file (`~/.claude/AGENTS.md`, with
`~/.claude/CLAUDE.md` symlinked to it) usually carries personal rules that must not live in a
public repo. So instead of a symlink, that file stays a private real file and pulls the hub in
with an import line:

```
@/absolute/path/to/agent-rules/core.md
```

`install.sh` creates a core-only stub if the file is absent and never overwrites an existing
one. Shared rules land in `core.md`; personal rules stay in the private overlay.

## Cross-agent symlink scheme

Keep every agent's home dir pointed at shared canonical files rather than maintaining
parallel copies. The rule of thumb: **one real file, everything else a symlink to it.** When
you add a new shared artifact, add the canonical copy once and link the other locations —
`doctor.sh` (or a quick `readlink` check) confirms nothing silently became a real file again.

## Staying in sync across machines

This repo *is* the sync source for the generic layer: clone it on each machine, run
`setup/install.sh`, and the home-level symlinks re-point at the tracked canonical files.
Machine-specific and private artifacts (secrets, the recall corpus + `memory.db`, voice
profiles) are deliberately **not** tracked — they stay local and never travel through the repo.
