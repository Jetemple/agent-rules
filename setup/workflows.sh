#!/usr/bin/env bash

workflow_private_map() {
  printf '%s/agent-rules/workflow-map' "${XDG_CONFIG_HOME:-$HOME/.config}"
}

workflow_entries() {
  local repo="$1" private_map public_map
  private_map="$(workflow_private_map)"
  public_map="$repo/workflow-map"

  if [ -f "$private_map" ]; then
    set -- "$public_map" "$private_map"
  else
    set -- "$public_map"
  fi

  awk '
    function add(origin) {
      if (NF == 0 || $1 ~ /^#/) return
      if (NF != 3) {
        printf "invalid workflow record: %s:%d\n", FILENAME, FNR > "/dev/stderr"
        invalid = 1
        return
      }
      name = $1
      if (!(name in position)) {
        order[++count] = name
        position[name] = count
      }
      origins[name] = origin
      sources[name] = $2
      targets[name] = $3
    }

    FILENAME == ARGV[1] { add("public"); next }
    { add("private") }

    END {
      if (invalid) exit 1
      for (i = 1; i <= count; i++) {
        name = order[i]
        print origins[name], name, sources[name], targets[name]
      }
    }
  ' "$@"
}

workflow_source() {
  local repo="$1" origin="$2" source="$3"
  if [ "$origin" = public ]; then
    printf '%s/%s' "$repo" "$source"
  else
    printf '%s' "${source/#\~/$HOME}"
  fi
}

workflow_catalog() {
  case "$1" in
    agents) printf '%s/.agents/skills' "$HOME" ;;
    codex) printf '%s/.codex/skills' "$HOME" ;;
    claude) printf '%s/.claude/skills' "$HOME" ;;
    *) return 1 ;;
  esac
}
