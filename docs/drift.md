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
- **`map`** — one line per tool: `tool  load-point  hub-file  mode`. The load-point is where
  that tool reads its global instructions (`~/.codex/AGENTS.md`, `~/.config/opencode/AGENTS.md`,
  `~/.gemini/GEMINI.md`, …). `mode` is how install.sh wires it (see below).
- **`setup/install.sh`** — reads the map and wires each *installed* tool's load-point back at
  the hub file. Skips tools whose config dir doesn't exist.

### Two wiring modes

Not every tool can layer a second instruction file on top of a shared one. `mode` picks how
install.sh wires each load-point:

- **`link`** — symlink the load-point straight at `core.md`. Edit `core.md` and every link-mode
  tool sees it instantly (live sync). The tradeoff: a symlink is only the shared file, so there
  is nowhere to add tool-specific or personal rules. Use it when the tool needs the shared rules
  and nothing more.
- **`block`** — write a **real file** at the load-point containing a managed fenced region:

  ```
  # >>> agent-rules hub (managed by install.sh — do not edit) >>>
  …core.md, verbatim…
  # <<< agent-rules hub <<<

  …your private overlay rules live here, outside the fence…
  ```

  install.sh rewrites **only** what's between the markers; anything outside survives every
  re-run. This is the layering pattern (conda/pyenv/nix use it on `.zshrc`). The tradeoff: it's
  not live — after editing `core.md`, re-run `setup/install.sh` to refresh the block.
  `setup/doctor.sh` checksums the fenced region against `core.md` and **FAILs on drift**, so a
  stale block is caught, not silent. Converting a `link`-mode load-point to `block` is safe (the
  old symlink held no private content); adopting a pre-existing real file preserves it below the
  fence, and a file with a mismatched marker is backed up to `.bak` before rebuild.

**Why Codex is `block`:** Codex reads its global `~/.codex/AGENTS.md` but (as of v0.143.0) does
not expand `@import` lines and has no extra-instructions config key — so a symlink would give it
*only* the shared rules, with no way to add private Codex rules. The managed block gives it both:
shared rules inside the fence, private rules below it, in one file it natively reads.

Claude Code is the other special case, and it goes the opposite way: its global file
(`~/.claude/AGENTS.md`, with `~/.claude/CLAUDE.md` symlinked to it) carries personal rules that
must not live in a public repo, and Claude *does* expand imports. So it stays a private real file
that pulls the hub in with one import line:

```
@/absolute/path/to/agent-rules/core.md
```

`install.sh` creates a core-only stub if the file is absent and never overwrites an existing one.
Either way — `@import` (Claude) or managed `block` (Codex) — shared rules come from `core.md` and
personal rules stay in the private overlay, never in the public repo.

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
