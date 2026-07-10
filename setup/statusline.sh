#!/usr/bin/env bash
# Generic status line for Claude Code (macOS/zsh). No host/employer references.
# Claude Code passes a JSON blob on stdin; we pull a few fields with a tolerant parser.
# Prints: <model> · <cwd basename> · <context% used, if available>, truecolor ANSI.
# install.sh seeds this as a one-time COPY into ~/.claude/statusline.sh (not a symlink) —
# it's meant to diverge per-device once seeded. Edit your local copy freely; edit this file
# only to change what NEW devices seed with.
set -uo pipefail

input="$(cat)"

# Tolerant field extraction: prefer jq if present, else fall back to grep/sed.
field() {  # field <jq-path> <regex-key> (string values)
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null
  else
    printf '%s' "$input" | grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed 's/.*:[[:space:]]*"\(.*\)"/\1/'
  fi
}

field_num() {  # field_num <jq-path> <regex-key> (bare numeric values, e.g. used_percentage)
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null
  else
    printf '%s' "$input" | grep -o "\"$2\"[[:space:]]*:[[:space:]]*[0-9.]*" | head -1 | sed 's/.*:[[:space:]]*//'
  fi
}

model="$(field '.model.display_name' 'display_name')"
[ -z "$model" ] && model="$(field '.model.id' 'id')"
[ -z "$model" ] && model="claude"

cwd="$(field '.workspace.current_dir' 'current_dir')"
[ -z "$cwd" ] && cwd="$PWD"
cwd_base="$(basename "$cwd")"

# Context usage is null early in a session (before the first API response); show it only if present.
pct="$(field_num '.context_window.used_percentage' 'used_percentage')"

# Truecolor-safe ANSI; degrades harmlessly to visible escape codes on very old terminals.
RESET=$'\033[0m'
DIM=$'\033[2m'
CYAN=$'\033[1;36m'
GRAY=$'\033[0;37m'
GREEN=$'\033[1;32m'
YELLOW=$'\033[1;33m'
RED=$'\033[1;31m'

sep="${DIM} · ${RESET}"
line="${CYAN}${model}${RESET}${sep}${GRAY}${cwd_base}${RESET}"

if [ -n "$pct" ]; then
  pct_int="${pct%%.*}"
  if [ "$pct_int" -lt 50 ] 2>/dev/null; then
    ctx_color="$GREEN"
  elif [ "$pct_int" -lt 80 ] 2>/dev/null; then
    ctx_color="$YELLOW"
  else
    ctx_color="$RED"
  fi
  line="${line}${sep}${ctx_color}${pct}% ctx${RESET}"
fi

printf '%s\n' "$line"
