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

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

echo "== dry-run (must not touch anything) =="
"$REPO/setup/install.sh" --dry-run
[ ! -e "$HOME/.claude/statusline.sh" ] || fail "dry-run seeded statusline.sh"
pass "dry-run made no changes"

echo "== install =="
"$REPO/setup/install.sh"

echo "== doctor: expect a healthy, fully-wired install (recall is the one expected warn) =="
"$REPO/setup/doctor.sh" || fail "doctor.sh reported a real FAIL (see output above)"
pass "doctor.sh clean"

echo "== spot-check the wiring doctor is supposed to verify =="
[ -L "$HOME/.gemini/GEMINI.md" ] || fail "gemini not symlinked (mode=link)"
[ -L "$HOME/.config/opencode/AGENTS.md" ] || fail "opencode not symlinked (mode=link)"
grep -qF '# >>> agent-rules hub' "$HOME/.codex/AGENTS.md" || fail "codex block not written (mode=block)"
[ -L "$HOME/.claude/CLAUDE.md" ] || fail "claude CLAUDE.md -> AGENTS.md symlink missing"
grep -q "^@$REPO/core.md" "$HOME/.claude/AGENTS.md" || fail "claude AGENTS.md missing hub import"
[ -x "$HOME/.claude/statusline.sh" ] || fail "statusline.sh not seeded/executable"
pass "hub wiring matches map"

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
