#!/usr/bin/env bash
# Prompt-template registry helpers (sourced by install.sh / doctor.sh / tests).
# Validates the WHOLE prompt-map before returning anything, so a malformed row anywhere
# means no links get installed (fail closed, never a partial install).

prompt_target_dir() {
  case "$1" in
    pi) printf '%s/.pi/agent/prompts' "$HOME" ;;
    *) return 1 ;;
  esac
}

prompt_entries() {  # prompt_entries <repo> -> "name source targets" lines; exit 1 if any row is bad
  local repo="$1" invalid=0 out="" name source targets target extra map
  local _targets
  map="$repo/prompt-map"
  [ -f "$map" ] || { echo "prompt map missing: $map" >&2; return 1; }
  while read -r name source targets extra; do
    case "$name" in ''|\#*) continue ;; esac
    if [ -z "$source" ] || [ -z "$targets" ] || [ -n "${extra:-}" ]; then
      echo "invalid prompt record: $map ($name)" >&2; invalid=1; continue
    fi
    case "$source" in
      *.md) ;;
      *) echo "invalid prompt source (must be .md): $name -> $source" >&2; invalid=1 ;;
    esac
    [ -f "$repo/$source" ] || { echo "prompt source missing: $name -> $repo/$source" >&2; invalid=1; }
    _targets=()
    IFS=, read -r -a _targets <<< "$targets"
    for target in "${_targets[@]}"; do
      prompt_target_dir "$target" > /dev/null || {
        echo "unknown prompt target: $name -> '$target'" >&2; invalid=1
      }
    done
    out+="$name $source $targets"$'\n'
  done < "$map"
  [ "$invalid" -eq 0 ] || return 1
  printf '%s' "$out"
}
