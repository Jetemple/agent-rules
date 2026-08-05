#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
SETTINGS="$REPO/setup/settings.example.json"
DOC="$REPO/docs/compaction.md"
CORE="$REPO/core.md"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

python3 - "$SETTINGS" <<'PY' || fail "settings.example.json does not define the 200k Claude contract"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    settings = json.load(handle)

assert settings["autoCompactEnabled"] is True
assert settings["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "200000"
assert settings["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == "100"
assert "autoCompactWindow" not in settings
PY

grep -qF '"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"' "$DOC" \
  || fail "Claude's documented compaction window is not 200000"
grep -qF '"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "100"' "$DOC" \
  || fail "Claude's documented percentage override is not 100"
grep -qF 'model_auto_compact_token_limit = 200000' "$DOC" \
  || fail "Codex's documented compaction limit is not 200000"
grep -qF '**Compaction continuity.**' "$CORE" \
  || fail "core.md does not define the shared compaction-continuity rule"

echo "PASS: compaction config and continuity guidance"
