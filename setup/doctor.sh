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

echo "== install: home symlinks point at THIS repo =="
# install.sh links these two. Absent -> not installed yet (warn). Present but wrong -> FAIL.
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
check_link "$HOME/.claude/AGENTS.md"    "$REPO/AGENTS.md"
check_link "$HOME/.claude/statusline.sh" "$REPO/setup/statusline.sh"

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
