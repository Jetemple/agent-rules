#!/usr/bin/env bash
# Idempotent, inspect-then-act installer (macOS/zsh). Wires every installed agent tool back to
# this hub by symlinking each tool's instruction load-point at a hub file (per ../map).
# Refuses to overwrite a real (non-symlink) file. Supports --dry-run. Re-run is safe.
#
# NEVER touches a live ~/.claude/settings.json (real permissions, plugins) — copy
# setup/settings.example.json by hand. Claude's rules file is treated as a PERSONAL overlay:
# this script creates a core-only stub if absent, and never clobbers real personal content.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

expand() { printf '%s' "${1/#\~/$HOME}"; }  # expand a leading ~ read from the map

link() {  # link <abs-src> <dest>  — idempotent; refuses to clobber a real file
  local src="$1" dest="$2"
  if [ ! -e "$src" ]; then echo "skip (missing src): $src"; return; fi
  if [ -L "$dest" ]; then
    local cur; cur="$(readlink "$dest")"
    if [ "$cur" = "$src" ]; then echo "ok (already linked): $dest"; return; fi
    echo "relink: $dest -> $src (was $cur)"
    [ "$DRY" -eq 1 ] || ln -sfn "$src" "$dest"; return
  fi
  if [ -e "$dest" ]; then
    echo "REFUSE: $dest is a real file (not a symlink). Back it up and remove it first." >&2; return
  fi
  echo "link: $dest -> $src"
  [ "$DRY" -eq 1 ] || { mkdir -p "$(dirname "$dest")"; ln -s "$src" "$dest"; }
}

echo "== tools (from map): link each installed tool's load-point -> hub =="
# Only wire a tool whose home dir already exists (i.e. the tool is installed on this machine).
while read -r tool loadpoint hubfile; do
  case "$tool" in ''|\#*) continue;; esac
  dest="$(expand "$loadpoint")"
  if [ ! -d "$(dirname "$dest")" ]; then   # tool's config dir absent -> tool not installed
    echo "skip (not installed): $tool ($dest)"; continue
  fi
  link "$REPO/$hubfile" "$dest"
done < "$REPO/map"

echo
echo "== claude: personal overlay (core-only stub if absent; never clobbered) =="
CLAUDE_DIR="$HOME/.claude"
if [ -d "$CLAUDE_DIR" ]; then
  if [ ! -e "$CLAUDE_DIR/AGENTS.md" ]; then
    echo "create: $CLAUDE_DIR/AGENTS.md (core-only stub)"
    if [ "$DRY" -eq 0 ]; then
      printf '# Personal agent rules (Claude)\n\n@%s/core.md\n\n# Add Claude-specific / personal rules below (this file is private, never committed).\n' "$REPO" > "$CLAUDE_DIR/AGENTS.md"
    fi
  else
    echo "ok (personal file present, left untouched): $CLAUDE_DIR/AGENTS.md"
    echo "   -> ensure it contains a line:  @$REPO/core.md"
  fi
  # CLAUDE.md must resolve to AGENTS.md (relative link within ~/.claude).
  if [ -L "$CLAUDE_DIR/CLAUDE.md" ] && [ "$(readlink "$CLAUDE_DIR/CLAUDE.md")" = "AGENTS.md" ]; then
    echo "ok (already linked): $CLAUDE_DIR/CLAUDE.md -> AGENTS.md"
  elif [ -e "$CLAUDE_DIR/CLAUDE.md" ] && [ ! -L "$CLAUDE_DIR/CLAUDE.md" ]; then
    echo "REFUSE: $CLAUDE_DIR/CLAUDE.md is a real file. Move it into AGENTS.md, then re-run." >&2
  else
    echo "link: $CLAUDE_DIR/CLAUDE.md -> AGENTS.md"
    [ "$DRY" -eq 0 ] && ln -s AGENTS.md "$CLAUDE_DIR/CLAUDE.md"
  fi
else
  echo "skip (not installed): claude (~/.claude absent)"
fi

echo
echo "== statusline (optional) =="
link "$REPO/setup/statusline.sh" "$HOME/.claude/statusline.sh"

echo
echo "== privacy guard: install pre-commit hook =="
HOOK_SRC="$REPO/setup/hooks/pre-commit"
HOOK_DEST="$REPO/.git/hooks/pre-commit"
[ "$DRY" -eq 0 ] && chmod +x "$REPO/check-privacy.sh" "$HOOK_SRC" 2>/dev/null
if [ -d "$REPO/.git" ]; then
  link "$HOOK_SRC" "$HOOK_DEST"
else
  echo "skip: not a git checkout, no .git/hooks to install into"
fi

# The guard's identity patterns live OUTSIDE the repo (so the guard never encodes who you
# are). Create a commented stub if absent; never touch an existing one.
PRIV="$HOME/.config/agent-rules/private-patterns"
if [ -f "$PRIV" ]; then
  echo "ok (present, left untouched): $PRIV"
else
  echo "create: $PRIV (stub — add your identity patterns, one regex per line)"
  if [ "$DRY" -eq 0 ]; then
    mkdir -p "$(dirname "$PRIV")"
    cat > "$PRIV" <<'EOF'
# Private privacy-guard patterns (extended regex, one per line, case-insensitive).
# Read by agent-rules/check-privacy.sh. This file lives OUTSIDE the repo on purpose:
# it holds identity the public guard script must never encode. Do not commit it anywhere.
# Examples (uncomment and edit):
#   first[[:space:]._-]*last
#   my-private-email-localpart
#   my-employer-name
#   my-local-username
EOF
  fi
fi

echo
echo "Done. (dry-run=$DRY)  Run ./setup/doctor.sh to verify, ./check-privacy.sh to scan."
