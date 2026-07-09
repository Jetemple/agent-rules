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

- **Global** — `~/.claude/CLAUDE.md` → `~/.claude/AGENTS.md`, and point Codex's global
  `~/.codex/AGENTS.md` at the same canonical file.
- **Project** — the repo's `CLAUDE.md` → its `AGENTS.md`.

Repo files are inert until install creates the home-level symlinks. `setup/doctor.sh` verifies
both the global and project load paths resolve.

## Cross-agent symlink scheme

Keep the two agents' home dirs pointed at shared canonical files rather than maintaining
parallel copies. The rule of thumb: **one real file, everything else a symlink to it.** When
you add a new shared artifact, add the canonical copy once and link the other locations —
`doctor.sh` (or a quick `readlink` check) confirms nothing silently became a real file again.

## Staying in sync across machines

This repo *is* the sync source for the generic layer: clone it on each machine, run
`setup/install.sh`, and the home-level symlinks re-point at the tracked canonical files.
Machine-specific and private artifacts (secrets, the recall corpus + `memory.db`, voice
profiles) are deliberately **not** tracked — they stay local and never travel through the repo.
