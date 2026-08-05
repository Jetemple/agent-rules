# Drift: canonical files, symlinks, and staying in sync

Multiple agents read multiple instruction files, and you run on more than one machine.
Without a scheme they **drift** — Claude reads one thing, Codex another, laptop disagrees
with desktop. One source of truth fixes it.

## Canonical-file model

Claude Code reads `CLAUDE.md`; Codex reads `AGENTS.md`; neither reads the other by default.
Pick one canonical file and symlink the rest:

- **`AGENTS.md` is canonical** (the emerging cross-tool standard).
- **`CLAUDE.md` is a symlink → `AGENTS.md`** (`ln -s AGENTS.md CLAUDE.md`).

Now a single edit reaches every runtime. Applies at both scopes: **global** (each tool's
load-point symlinks at `core.md` in this repo) and **project** (this repo's `CLAUDE.md` →
`AGENTS.md`). Repo files are inert until `setup/install.sh` creates the home-level links;
`setup/doctor.sh` verifies both scopes resolve.

## The hub model (global scope)

- **`core.md`** — the shared, tool-agnostic rules; the only file you edit to change behavior
  everywhere.
- **`map`** — one line per tool: `tool  load-point  hub-file  mode`. `load-point` is where
  that tool reads its global instructions; `mode` is how install.sh wires it (below).
- **`setup/install.sh`** — reads the map and wires each *installed* tool's load-point back at
  the hub file. Skips tools whose config dir doesn't exist.

### Two wiring modes

- **`link`** — symlink the load-point straight at `core.md`. Live sync on every edit, but the
  symlink *is* the shared file — nowhere to add tool-specific or personal rules. Use when the
  tool needs the shared rules and nothing more.
- **`block`** — write a **real file** containing a managed fenced region:

  ```
  # >>> agent-rules hub (managed by install.sh — do not edit) >>>
  …core.md, verbatim…
  # <<< agent-rules hub <<<

  …your private overlay rules live here, outside the fence…
  ```

  install.sh rewrites only what's between the markers; anything outside survives every re-run.
  Not live — after editing `core.md`, re-run install.sh to refresh. `doctor.sh` checksums the
  fenced region against `core.md` and fails on drift. Converting `link`→`block` is safe; a
  pre-existing real file is preserved below the fence; a mismatched-marker file is backed up
  to `.bak` before rebuild.

**Why Codex is `block`:** Codex (as of v0.143.0) doesn't expand `@import` lines and has no
extra-instructions key, so a symlink would give it only the shared rules — the managed block
gives it both. **Why Claude goes the other way:** its global file carries personal rules that
must not live in a public repo, and Claude *does* expand imports — so it stays a private real
file pulling the hub in with one line: `@/absolute/path/to/agent-rules/core.md`.
`install.sh` creates a core-only stub if absent and never overwrites an existing file.

## Staying in sync across machines

The repo *is* the sync source for the generic layer: clone on each machine, run
`setup/install.sh`, and the home-level links re-point at the tracked canonical files.
Machine-specific and private artifacts (secrets, the recall corpus + `memory.db`, voice
profiles) are deliberately **not** tracked — they stay local and never travel through the repo.
