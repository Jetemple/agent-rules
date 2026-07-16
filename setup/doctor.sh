#!/usr/bin/env bash
# Public health-check (macOS/zsh). Verifies both clone integrity AND that install.sh took.
# Does NOT depend on the private release gate (that lives outside the repo).
#
# Exit status:
#   0  everything that is set up is healthy (may include "not yet installed" warnings)
#   1  a real problem: broken canonical symlink, leaked private profile, or a home
#      symlink that exists but points somewhere other than this repo.
# Uses only POSIX tools (grep, not rg) so it runs on a bare machine.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fail=0
notinstalled=0

# grep -rIl over the tree, honoring the same exclusions the private gate uses. Prints
# matching paths (excluding this script + the two files that legitimately name the sentinel).
sentinel_hits() {
  grep -rIl 'AGENT-RULES-PRIVATE-VOICE-PROFILE' "$REPO" \
    --exclude-dir='.git' 2>/dev/null \
    | grep -v -e '/your-voice/template.md$' -e '/your-voice/SKILL.md$' -e '/setup/doctor.sh$' \
    || true
}

echo "== canonical-file model (clone integrity) =="
if [ -L "$REPO/CLAUDE.md" ] && [ "$(readlink "$REPO/CLAUDE.md")" = "AGENTS.md" ]; then
  echo "ok: CLAUDE.md -> AGENTS.md"
else
  echo "FAIL: CLAUDE.md is not a symlink to AGENTS.md"; fail=1
fi

echo "== no private voice profile in tree =="
hits="$(sentinel_hits)"
if [ -n "$hits" ]; then
  echo "FAIL: a private voice profile is present:"; echo "$hits" | sed 's/^/    /'; fail=1
else
  echo "ok: no private voice profile"
fi

echo "== hub install: each tool's load-point carries THIS repo's hub (per map) =="
# install.sh wires these. Tool not installed -> skip. Absent -> warn. Wrong/drifted -> FAIL.
check_link() {  # check_link <dest> <expected-src>
  local dest="$1" want="$2"
  if [ -L "$dest" ]; then
    local cur; cur="$(readlink "$dest")"
    if [ "$cur" = "$want" ]; then echo "ok: $dest -> $want"
    else echo "FAIL: $dest -> $cur (expected $want)"; fail=1; fi
  elif [ -e "$dest" ]; then
    # A real file here isn't corruption — install.sh deliberately refuses to clobber it.
    # It just means this dest is managed by something other than this repo.
    echo "warn: $dest is a real file (not linked; install.sh will refuse until moved)"; notinstalled=1
  else
    echo "warn: $dest not linked (run ./setup/install.sh)"; notinstalled=1
  fi
}

# Must match install.sh exactly.
BLOCK_BEGIN='# >>> agent-rules hub (managed by install.sh — do not edit) >>>'
BLOCK_END='# <<< agent-rules hub <<<'
check_block() {  # check_block <dest> <expected-src> — fenced region must equal hub file verbatim
  local dest="$1" want="$2"
  if [ ! -e "$dest" ]; then
    echo "warn: $dest has no managed block (run ./setup/install.sh)"; notinstalled=1; return
  fi
  if [ -L "$dest" ]; then
    echo "FAIL: $dest is a symlink but map says mode=block (run ./setup/install.sh)"; fail=1; return
  fi
  if ! grep -qF "$BLOCK_BEGIN" "$dest" || ! grep -qF "$BLOCK_END" "$dest"; then
    echo "FAIL: $dest is missing a managed-block marker (corrupt; re-run ./setup/install.sh)"; fail=1; return
  fi
  local got; got="$(awk -v b="$BLOCK_BEGIN" -v e="$BLOCK_END" '
    $0==b {inblk=1; next} $0==e {inblk=0; next} inblk {print}' "$dest")"
  if [ "$got" = "$(cat "$want")" ]; then
    echo "ok: $dest managed block matches $want"
  else
    echo "FAIL: $dest managed block has DRIFTED from $want (re-run ./setup/install.sh)"; fail=1
  fi
}
expand() { printf '%s' "${1/#\~/$HOME}"; }
while read -r tool loadpoint hubfile mode; do
  case "$tool" in ''|\#*) continue;; esac
  dest="$(expand "$loadpoint")"
  if [ ! -d "$(dirname "$dest")" ]; then
    echo "skip (not installed): $tool ($dest)"; continue
  fi
  case "${mode:-link}" in
    block) check_block "$dest" "$REPO/$hubfile" ;;
    link|'') check_link "$dest" "$REPO/$hubfile" ;;
    *) echo "FAIL: $tool has unknown mode '$mode' in map (want link|block)"; fail=1 ;;
  esac
done < "$REPO/map"

echo "== workflows: each effective registry entry is healthy =="
. "$REPO/setup/workflows.sh"
workflow_output=""
if ! workflow_output="$(workflow_entries "$REPO")"; then
  echo "FAIL: workflow map is invalid; no workflow entries were checked." >&2
  fail=1
else
  while read -r origin name source targets; do
    [ -n "$origin" ] || continue
    src="$(workflow_source "$REPO" "$origin" "$source")"
    [ -d "$src" ] || { echo "FAIL: workflow '$name' source missing: $src"; fail=1; continue; }
    workflow_targets=()
    IFS=, read -r -a workflow_targets <<< "$targets"
    for target in "${workflow_targets[@]}"; do
      catalog="$(workflow_catalog "$target")" || {
        echo "FAIL: workflow '$name' has unknown target '$target'"; fail=1; continue
      }
      dest="$catalog/$name"
      if [ -d "$dest" ] && [ ! -L "$dest" ] && \
         [ "$(cd "$src" && pwd -P)" = "$(cd "$dest" && pwd -P)" ]; then
        echo "ok: $dest is the selected source directory"
      else
        check_link "$dest" "$src"
      fi
    done
  done <<< "$workflow_output"
fi

echo "== claude: personal overlay imports the hub =="
# Claude is special-cased (see map header): ~/.claude/AGENTS.md is a PERSONAL real file that
# @imports core.md, and ~/.claude/CLAUDE.md symlinks to it.
if [ -d "$HOME/.claude" ]; then
  if [ -f "$HOME/.claude/AGENTS.md" ]; then
    if grep -q "^@$REPO/core.md" "$HOME/.claude/AGENTS.md"; then
      echo "ok: ~/.claude/AGENTS.md imports $REPO/core.md"
    else
      echo "warn: ~/.claude/AGENTS.md has no '@$REPO/core.md' line — hub rules not loaded by Claude"; notinstalled=1
    fi
  else
    echo "warn: ~/.claude/AGENTS.md missing (run ./setup/install.sh to create the stub)"; notinstalled=1
  fi
  if [ -L "$HOME/.claude/CLAUDE.md" ] && [ "$(readlink "$HOME/.claude/CLAUDE.md")" = "AGENTS.md" ]; then
    echo "ok: ~/.claude/CLAUDE.md -> AGENTS.md"
  else
    echo "warn: ~/.claude/CLAUDE.md is not a symlink to AGENTS.md"; notinstalled=1
  fi
else
  echo "skip (not installed): claude (~/.claude absent)"
fi
check_seeded() {  # check_seeded <dest> — one-time-copy target; just needs to exist + be executable
  local dest="$1"
  if [ -x "$dest" ]; then echo "ok: $dest present and executable"
  elif [ -e "$dest" ]; then echo "warn: $dest present but not executable (chmod +x it)"; notinstalled=1
  else echo "warn: $dest not seeded (run ./setup/install.sh)"; notinstalled=1; fi
}
check_seeded "$HOME/.claude/statusline.sh"

echo "== privacy guard =="
if [ -x "$REPO/check-privacy.sh" ]; then echo "ok: check-privacy.sh present + executable"
else echo "FAIL: check-privacy.sh missing or not executable"; fail=1; fi
if [ -L "$REPO/.git/hooks/pre-commit" ] && [ "$(readlink "$REPO/.git/hooks/pre-commit")" = "$REPO/setup/hooks/pre-commit" ]; then
  echo "ok: pre-commit hook installed (ours)"
elif [ -e "$REPO/.git/hooks/pre-commit" ]; then
  echo "warn: a pre-commit hook exists but is NOT this repo's guard hook"; notinstalled=1
else
  echo "warn: no pre-commit hook (run ./setup/install.sh)"; notinstalled=1
fi
if [ -f "$HOME/.config/agent-rules/private-patterns" ]; then
  echo "ok: private pattern file present"
else
  echo "warn: no ~/.config/agent-rules/private-patterns (guard runs generic checks only)"; notinstalled=1
fi

echo "== recall (skipped if not set up) =="
if [ -d "$REPO/tools/recall/.venv" ]; then echo "ok: recall venv present"
else echo "warn: no tools/recall/.venv (run the recall bootstrap in docs/setup.md)"; notinstalled=1; fi
if [ -f "$HOME/.recall/config.json" ]; then echo "ok: ~/.recall/config.json present"
else echo "warn: no ~/.recall/config.json (copy config.example.json there)"; notinstalled=1; fi
if [ -f "$HOME/.recall/memory.db" ]; then echo "ok: ~/.recall/memory.db index built"
else echo "warn: no ~/.recall/memory.db (run: python3 tools/recall/recall.py index)"; notinstalled=1; fi

echo
if [ "$fail" -ne 0 ]; then
  echo "DOCTOR FOUND ISSUES"; exit 1
elif [ "$notinstalled" -ne 0 ]; then
  echo "DOCTOR OK (clone healthy; some install steps not done yet — see warnings above)"
else
  echo "DOCTOR OK (clone healthy and fully installed)"
fi
