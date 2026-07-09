#!/usr/bin/env bash
# Idempotent, inspect-then-act installer (macOS/zsh). Creates home-level symlinks from this
# repo into ~/.claude and ~/.codex. Refuses to overwrite a real (non-symlink) file.
# Supports --dry-run. No transactional rollback (YAGNI): re-run is safe.
#
# NEVER reads or overwrites a live ~/.claude/settings.json (real permissions, plugins). Copy
# setup/settings.example.json by hand and edit it — this script does not touch settings.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

link() {  # link <src-in-repo> <dest>
  local src="$REPO/$1" dest="$2"
  if [ ! -e "$src" ]; then echo "skip (missing src): $1"; return; fi
  if [ -L "$dest" ]; then
    local cur; cur="$(readlink "$dest")"
    if [ "$cur" = "$src" ]; then echo "ok (already linked): $dest"; return; fi
    echo "relink: $dest -> $src (was $cur)"
    [ "$DRY" -eq 1 ] || ln -sfn "$src" "$dest"
    return
  fi
  if [ -e "$dest" ]; then
    echo "REFUSE: $dest is a real file (not a symlink). Back it up and remove it first." >&2
    return
  fi
  echo "link: $dest -> $src"
  [ "$DRY" -eq 1 ] || { mkdir -p "$(dirname "$dest")"; ln -s "$src" "$dest"; }
}

# Example links — adjust to taste. Never touches a real ~/.claude/settings.json.
link "AGENTS.md"           "$HOME/.claude/AGENTS.md"
link "setup/statusline.sh" "$HOME/.claude/statusline.sh"

echo "Done. (dry-run=$DRY)  Run ./setup/doctor.sh to verify."
