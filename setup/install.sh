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

# Managed-block markers. install.sh owns everything BETWEEN them; the user owns everything
# outside. The literal strings are matched exactly by write_block and doctor.sh — do not reword.
BLOCK_BEGIN='# >>> agent-rules hub (managed by install.sh — do not edit) >>>'
BLOCK_END='# <<< agent-rules hub <<<'

write_block() {  # write_block <abs-src> <dest>  — real file; rewrites ONLY the fenced region
  local src="$1" dest="$2"
  if [ ! -e "$src" ]; then echo "skip (missing src): $src"; return; fi

  # Gather the content that must live OUTSIDE the fence (the user's private overlay).
  local outside=""
  if [ -L "$dest" ]; then
    # A prior link-mode install (or the user) symlinked this. Converting to block mode: the
    # symlink only ever pointed at core.md, so there is no private content to preserve.
    echo "convert (link -> block): $dest"
  elif [ -e "$dest" ]; then
    if grep -qF "$BLOCK_BEGIN" "$dest" && grep -qF "$BLOCK_END" "$dest"; then
      # Healthy managed file: keep everything except the old fenced region (re-emitted below).
      outside="$(awk -v b="$BLOCK_BEGIN" -v e="$BLOCK_END" '
        $0==b {inblk=1; next} $0==e {inblk=0; next} !inblk {print}' "$dest")"
      echo "update (managed block): $dest"
    elif grep -qF "$BLOCK_BEGIN" "$dest" || grep -qF "$BLOCK_END" "$dest"; then
      # Exactly one marker: file is corrupt/half-edited. Don't guess — back up, preserve whole.
      echo "REPAIR: $dest has a mismatched marker; backing up to $dest.bak and rebuilding." >&2
      [ "$DRY" -eq 1 ] || cp "$dest" "$dest.bak"
      outside="$(cat "$dest")"
    else
      # A real file with no fence yet (the tool's own rules, or a hand-made file). Preserve it
      # entirely as the private overlay, below the fence.
      echo "adopt (real file -> managed block, existing content preserved below fence): $dest"
      outside="$(cat "$dest")"
    fi
  else
    echo "create (managed block): $dest"
  fi

  [ "$DRY" -eq 1 ] && return

  # Strip leading blank lines from the overlay — the writer below re-adds the one separator
  # line, so keeping them would grow the gap by one line on every re-run.
  [ -n "$outside" ] && outside="$(printf '%s\n' "$outside" | sed -n '/[^[:space:]]/,$p')"

  mkdir -p "$(dirname "$dest")"
  local tmp; tmp="$(mktemp "${dest}.XXXXXX")"
  {
    printf '%s\n' "$BLOCK_BEGIN"
    cat "$src"
    printf '%s\n' "$BLOCK_END"
    [ -n "$outside" ] && printf '\n%s\n' "$outside"
  } > "$tmp"
  mv "$tmp" "$dest"   # atomic swap: readers never see a half-written file
}

echo "== tools (from map): wire each installed tool's load-point -> hub =="
# Only wire a tool whose home dir already exists (i.e. the tool is installed on this machine).
# mode column is optional; missing -> link (back-compat with older maps).
while read -r tool loadpoint hubfile mode; do
  case "$tool" in ''|\#*) continue;; esac
  dest="$(expand "$loadpoint")"
  if [ ! -d "$(dirname "$dest")" ]; then   # tool's config dir absent -> tool not installed
    echo "skip (not installed): $tool ($dest)"; continue
  fi
  case "${mode:-link}" in
    block) write_block "$REPO/$hubfile" "$dest" ;;
    link|'') link "$REPO/$hubfile" "$dest" ;;
    *) echo "REFUSE: $tool has unknown mode '$mode' in map (want link|block)" >&2 ;;
  esac
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

copy_once() {  # copy_once <abs-src> <dest> — one-time seed; never touches an existing dest again
  local src="$1" dest="$2"
  if [ ! -e "$src" ]; then echo "skip (missing src): $src"; return; fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    echo "ok (already seeded, left untouched for local edits): $dest"; return
  fi
  echo "seed: $dest (copied from $src, not linked — free to diverge per-device)"
  [ "$DRY" -eq 1 ] || { mkdir -p "$(dirname "$dest")"; cp "$src" "$dest"; chmod +x "$dest"; }
}

echo
echo "== statusline (optional; seeded once as a real file, not symlinked — meant to diverge per-device) =="
copy_once "$REPO/setup/statusline.sh" "$HOME/.claude/statusline.sh"

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
