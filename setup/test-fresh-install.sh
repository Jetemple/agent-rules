#!/usr/bin/env bash
# Fresh-machine smoke test for install.sh/doctor.sh. Runs entirely inside a scratch
# $HOME and a private COPY of this repo, so it can never touch your real dotfiles or
# working tree no matter what install.sh does. Safe to run directly, but a clean
# container gives the strongest guarantee (no leakage from whatever's already on your
# real machine):
#
#   docker run --rm -v "$PWD":/repo:ro -w /tmp ubuntu:24.04 \
#     bash /repo/setup/test-fresh-install.sh /repo
#
# (bind-mounted read-only on purpose — the script copies out of it, never writes back)
set -euo pipefail

REPO_SRC="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

REPO="$WORK/repo"
cp -R "$REPO_SRC" "$REPO"
export HOME="$WORK/home"
mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.gemini" "$HOME/.config/opencode"
mkdir -p "$HOME/.private/wrap" "$HOME/.config/agent-rules" "$HOME/.codex/skills/your-voice"
printf '%s\n' 'wrap ~/.private/wrap agents,codex,claude' \
  > "$HOME/.config/agent-rules/workflow-map"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

echo "== malformed private workflow map: refuse before installing any workflow links =="
MALFORMED_HOME="$WORK/malformed-home"
mkdir -p "$MALFORMED_HOME/.claude" "$MALFORMED_HOME/.codex" \
  "$MALFORMED_HOME/.gemini" "$MALFORMED_HOME/.config/opencode" \
  "$MALFORMED_HOME/.config/agent-rules"
printf '%s\n' \
  'local ~/.private/local agents' \
  'malformed-record' \
  > "$MALFORMED_HOME/.config/agent-rules/workflow-map"
if HOME="$MALFORMED_HOME" "$REPO/setup/doctor.sh" > "$WORK/malformed-doctor.log" 2>&1; then
  fail "doctor.sh accepted a malformed private workflow map"
fi
if HOME="$MALFORMED_HOME" "$REPO/setup/install.sh" > "$WORK/malformed-install.log" 2>&1; then
  fail "install.sh accepted a malformed private workflow map"
fi
grep -qF "REFUSE: workflow map is invalid; no workflow links were installed." \
  "$WORK/malformed-install.log" \
  || fail "malformed workflow map refusal was not reported"
for catalog in .agents .codex .claude; do
  [ ! -L "$MALFORMED_HOME/$catalog/skills/handoff" ] \
    || fail "$catalog workflow link was partially installed from a malformed map"
done
pass "malformed private workflow map fails without partial workflow installation"

echo "== dry-run (must not touch anything) =="
"$REPO/setup/install.sh" --dry-run
[ ! -e "$HOME/.claude/statusline.sh" ] || fail "dry-run seeded statusline.sh"
pass "dry-run made no changes"

echo "== install =="
"$REPO/setup/install.sh"

echo "== doctor: expect a healthy, fully-wired install (recall is the one expected warn) =="
"$REPO/setup/doctor.sh" || fail "doctor.sh reported a real FAIL (see output above)"
pass "doctor.sh clean"

echo "== installer: canonicalize equivalent relative workflow symlinks =="
ln -sfn ../../../repo/workflows/handoff "$HOME/.agents/skills/handoff"
"$REPO/setup/install.sh"
[ "$(readlink "$HOME/.agents/skills/handoff")" = "$REPO/workflows/handoff" ] \
  || fail "installer left an equivalent relative workflow symlink non-canonical"
"$REPO/setup/doctor.sh" || fail "doctor rejected the canonicalized workflow link"
pass "installer canonicalizes equivalent relative workflow symlinks"

echo "== doctor: reject drifted workflow links and recover after repair =="
ln -sfn "$REPO/workflows/wrap" "$HOME/.agents/skills/wrap"
if "$REPO/setup/doctor.sh"; then fail "doctor accepted an incorrect workflow link"; fi
"$REPO/setup/install.sh"
"$REPO/setup/doctor.sh" || fail "doctor remained unhealthy after repair"
pass "doctor detects workflow drift and installer repairs it"

echo "== spot-check the wiring doctor is supposed to verify =="
[ -L "$HOME/.gemini/GEMINI.md" ] || fail "gemini not symlinked (mode=link)"
[ -L "$HOME/.config/opencode/AGENTS.md" ] || fail "opencode not symlinked (mode=link)"
grep -qF '# >>> agent-rules hub' "$HOME/.codex/AGENTS.md" || fail "codex block not written (mode=block)"
[ -L "$HOME/.claude/CLAUDE.md" ] || fail "claude CLAUDE.md -> AGENTS.md symlink missing"
grep -q "^@$REPO/core.md" "$HOME/.claude/AGENTS.md" || fail "claude AGENTS.md missing hub import"
[ -x "$HOME/.claude/statusline.sh" ] || fail "statusline.sh not seeded/executable"
pass "hub wiring matches map"

for catalog in .agents .codex .claude; do
  [ "$(readlink "$HOME/$catalog/skills/handoff")" = "$REPO/workflows/handoff" ] \
    || fail "$catalog handoff workflow not linked"
  [ "$(readlink "$HOME/$catalog/skills/wrap")" = "$HOME/.private/wrap" ] \
    || fail "$catalog private wrap override not linked"
done
[ -d "$HOME/.codex/skills/your-voice" ] && [ ! -L "$HOME/.codex/skills/your-voice" ] \
  || fail "real workflow destination was clobbered"
pass "workflow links match the effective map without clobbering real destinations"

echo "== idempotency: re-running must not fail or change what's already correct =="
"$REPO/setup/install.sh" || fail "second install.sh run failed"
"$REPO/setup/doctor.sh" || fail "doctor.sh unhappy after a second install.sh run"
pass "install.sh is safe to re-run"

echo "== statusline is seeded ONCE then left alone (must survive a re-run untouched) =="
printf '#!/bin/sh\necho "MY CUSTOM STATUSLINE"\n' > "$HOME/.claude/statusline.sh"
"$REPO/setup/install.sh"
grep -q "MY CUSTOM STATUSLINE" "$HOME/.claude/statusline.sh" \
  || fail "install.sh clobbered a local statusline.sh edit"
pass "statusline.sh divergence survives a re-run"

echo
echo "ALL FRESH-INSTALL CHECKS PASSED"
