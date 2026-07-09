#!/usr/bin/env bash
# Minimal, generic status line for Claude Code (macOS/zsh). No host/employer references.
# Claude Code passes a JSON blob on stdin; we pull a few fields with a tolerant parser.
# Prints: <model> · <cwd basename> · <context% used, if available>
set -uo pipefail

input="$(cat)"

# Tolerant field extraction: prefer jq if present, else fall back to grep/sed.
field() {  # field <jq-path> <regex-key>
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null
  else
    printf '%s' "$input" | grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed 's/.*:[[:space:]]*"\(.*\)"/\1/'
  fi
}

model="$(field '.model.display_name' 'display_name')"
[ -z "$model" ] && model="$(field '.model.id' 'id')"
[ -z "$model" ] && model="claude"

cwd="$(field '.workspace.current_dir' 'current_dir')"
[ -z "$cwd" ] && cwd="$PWD"
cwd_base="$(basename "$cwd")"

# Context usage is optional and version-dependent; show it only if present.
pct="$(field '.context.used_pct' 'used_pct')"

line="$model · $cwd_base"
[ -n "$pct" ] && line="$line · ${pct}% ctx"
printf '%s\n' "$line"
