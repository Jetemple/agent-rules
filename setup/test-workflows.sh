#!/usr/bin/env bash
set -euo pipefail

REPO_SRC="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

REPO="$WORK/repo"
HOME="$WORK/home"
export HOME
mkdir -p "$REPO/setup" "$HOME/.config/agent-rules"
cp "$REPO_SRC/setup/workflows.sh" "$REPO/setup/"
printf '%s\n' \
  'handoff workflows/handoff agents,codex,claude' \
  'wrap workflows/wrap agents,codex,claude' > "$REPO/workflow-map"
printf '%s\n' \
  'wrap ~/.private/wrap agents,codex' \
  'local ~/.private/local agents' > "$HOME/.config/agent-rules/workflow-map"

. "$REPO/setup/workflows.sh"

expected="public handoff workflows/handoff agents,codex,claude
private wrap ~/.private/wrap agents,codex
private local ~/.private/local agents"
[ "$(workflow_entries "$REPO")" = "$expected" ]
[ "$(workflow_source "$REPO" public workflows/handoff)" = "$REPO/workflows/handoff" ]
# shellcheck disable=SC2088 # The resolver must receive, then expand, the literal leading tilde.
[ "$(workflow_source "$REPO" private '~/.private/wrap')" = "$HOME/.private/wrap" ]
[ "$(workflow_catalog agents)" = "$HOME/.agents/skills" ]
[ "$(workflow_catalog codex)" = "$HOME/.codex/skills" ]
[ "$(workflow_catalog claude)" = "$HOME/.claude/skills" ]

while read -r name source targets; do
  case "$name" in ''|\#*) continue ;; esac
  skill="$REPO_SRC/$source/SKILL.md"
  [ -f "$skill" ] || { echo "FAIL: missing registered skill: $skill" >&2; exit 1; }
  awk -v expected_name="$name" '
    NR == 1 && $0 != "---" { exit 1 }
    NR > 1 && $0 == "---" { exit found_name && found_description ? 0 : 1 }
    NR > 1 && $1 == "name:" && $2 == expected_name { found_name=1 }
    NR > 1 && $1 == "description:" && NF > 1 { found_description=1 }
    END { if (!found_name || !found_description) exit 1 }
  ' "$skill" || {
    echo "FAIL: invalid SKILL.md frontmatter for registered workflow '$name'" >&2
    exit 1
  }
done < "$REPO_SRC/workflow-map"
