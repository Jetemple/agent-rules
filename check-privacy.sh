#!/usr/bin/env bash
# Privacy guard: scan everything a commit could include for personal data and secrets.
# Exit 1 (with a report) if anything leaks; exit 0 if clean. Runs on stock macOS bash 3.2
# (no mapfile, no bash-4isms) so it works inside a git hook on a bare machine.
#
# Two pattern layers:
#   1. GENERIC patterns baked in below — secrets, key material, personal-email domains,
#      hardcoded home paths, phone numbers. Nothing identifying anyone.
#   2. PRIVATE patterns read from ~/.config/agent-rules/private-patterns (one extended
#      regex per line, `#` comments). That file holds YOUR identity (name, handles,
#      employer) and lives OUTSIDE the repo, so the guard itself never encodes who you
#      are. install.sh creates a commented stub; fill it in.
#
# Scope: tracked files + untracked-but-not-ignored files (exactly what a commit could
# include), file CONTENTS and file NAMES both. Gitignored private overlays are not scanned.
#
# This is a denylist, not a proof of safety. The second layer of defense is an agent
# review of the diff before any push (see AGENTS.md). Err toward flagging.
set -uo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
PRIVATE_FILE="${AGENT_RULES_PRIVATE_PATTERNS:-$HOME/.config/agent-rules/private-patterns}"

# Generic patterns (extended regex, matched case-insensitively). Written so they cannot
# match their own source text here.
PATTERNS=(
  '-----BEGIN [A-Z ]{0,12}PRIVATE KEY'                    # PEM key material
  'sk-ant-[A-Za-z0-9_-]{8}'                               # Anthropic API key
  'sk-[A-Za-z0-9]{20}'                                    # OpenAI-style API key
  'gh[pousr]_[A-Za-z0-9]{20}'                             # GitHub token
  'AKIA[0-9A-Z]{16}'                                      # AWS access key
  'xox[baprs]-[A-Za-z0-9-]{10}'                           # Slack token
  '[A-Za-z0-9._%+-]+@(gmail|googlemail|yahoo|hotmail|outlook|icloud|proton|protonmail)\.com'
  '/Users/[A-Za-z0-9_.-]{2,}'                             # hardcoded macOS home path (use ~ or $HOME)
  '/home/[A-Za-z0-9_.-]{2,}'                              # hardcoded linux home path
  '\+?1?[[:space:]-]?\(?[0-9]{3}\)?[[:space:]-][0-9]{3}[[:space:]-][0-9]{4}'  # US phone
)

# Layer in the private identity patterns, if present.
nprivate=0
if [ -f "$PRIVATE_FILE" ]; then
  while IFS= read -r line; do
    case "$line" in ''|\#*) continue;; esac
    PATTERNS+=("$line")
    nprivate=$((nprivate + 1))
  done < "$PRIVATE_FILE"
  if [ "$nprivate" -eq 0 ]; then
    echo "warn: $PRIVATE_FILE has no active patterns (still the stub?) — generic checks only." >&2
  fi
else
  echo "warn: no private pattern file at $PRIVATE_FILE — generic checks only." >&2
  echo "      Create it (one regex per line: your name, handles, employer) or run install.sh." >&2
fi

# One combined alternation: a single grep per file, and the report line shows what leaked.
COMBINED=""
for pat in "${PATTERNS[@]}"; do
  COMBINED="${COMBINED:+$COMBINED|}($pat)"
done

fail=0
report=""
while IFS= read -r f; do
  [ -f "$REPO/$f" ] || continue
  # file NAME can leak too (e.g. notes named after a person)
  if printf '%s\n' "$f" | grep -qEi "$COMBINED"; then
    fail=1
    report+="  $f  (the FILENAME itself matches)"$'\n'
  fi
  hits="$(grep -nEiI "$COMBINED" "$REPO/$f" 2>/dev/null || true)"
  if [ -n "$hits" ]; then
    fail=1
    while IFS= read -r line; do
      report+="  $f:$line"$'\n'
    done <<< "$hits"
  fi
done < <(git -C "$REPO" ls-files --cached --others --exclude-standard 2>/dev/null)

# The loop above reads WORKTREE content. A commit ships INDEX blobs, which can differ
# (stage a leak, then clean the worktree copy). Scan the staged blobs too.
staged_hits="$(git -C "$REPO" grep -nEiI --cached -e "$COMBINED" 2>/dev/null || true)"
if [ -n "$staged_hits" ]; then
  fail=1
  while IFS= read -r line; do
    report+="  (staged) $line"$'\n'
  done <<< "$staged_hits"
fi

if [ "$fail" -ne 0 ]; then
  echo "PRIVACY CHECK FAILED — personal data or secrets in files a commit could include:" >&2
  printf '%s' "$report" >&2
  echo >&2
  echo "Scrub these (use ~ or \$HOME for paths; redact names/emails/keys) or gitignore the file." >&2
  exit 1
fi
echo "privacy check OK: no personal data or secrets in committable files"
