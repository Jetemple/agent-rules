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
export XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.gemini" "$HOME/.config/opencode" "$HOME/.pi/agent"
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
if HOME="$MALFORMED_HOME" XDG_CONFIG_HOME="$MALFORMED_HOME/.config" \
  "$REPO/setup/doctor.sh" > "$WORK/malformed-doctor.log" 2>&1; then
  fail "doctor.sh accepted a malformed private workflow map"
fi
if HOME="$MALFORMED_HOME" XDG_CONFIG_HOME="$MALFORMED_HOME/.config" \
  "$REPO/setup/install.sh" > "$WORK/malformed-install.log" 2>&1; then
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

echo "== malformed prompt map: refuse before installing any prompt-template links =="
PROMPT_HOME="$WORK/prompt-home"
PROMPT_REPO="$WORK/prompt-repo"
cp -R "$REPO_SRC" "$PROMPT_REPO"
mkdir -p "$PROMPT_HOME/.pi/agent" "$PROMPT_HOME/.claude"
printf '%s\n' 'goal prompts/goal.md pi' 'bogus prompts/missing.md pi' > "$PROMPT_REPO/prompt-map"
if HOME="$PROMPT_HOME" XDG_CONFIG_HOME="$PROMPT_HOME/.config" \
  "$PROMPT_REPO/setup/install.sh" > "$WORK/prompt-install.log" 2>&1; then
  fail "install.sh accepted a prompt map with a missing source"
fi
grep -qF "REFUSE: prompt map is invalid; no prompt-template links were installed." \
  "$WORK/prompt-install.log" || fail "malformed prompt map refusal was not reported"
[ ! -e "$PROMPT_HOME/.pi/agent/prompts/goal.md" ] \
  || fail "goal prompt link was partially installed from a malformed map"
if HOME="$PROMPT_HOME" XDG_CONFIG_HOME="$PROMPT_HOME/.config" \
  "$PROMPT_REPO/setup/doctor.sh" > /dev/null 2>&1; then
  fail "doctor.sh accepted a malformed prompt map"
fi
printf '%s\n' 'goal prompts/goal.md moon' > "$PROMPT_REPO/prompt-map"
if HOME="$PROMPT_HOME" XDG_CONFIG_HOME="$PROMPT_HOME/.config" \
  "$PROMPT_REPO/setup/install.sh" > /dev/null 2>&1; then
  fail "install.sh accepted an unknown prompt target"
fi
pass "malformed prompt map fails without partial prompt installation"

echo "== prompt templates: adopt an identical real file, preserve a differing one =="
mkdir -p "$HOME/.pi/agent/prompts"
cp "$REPO/prompts/goal.md" "$HOME/.pi/agent/prompts/goal.md"

echo "== dry-run (must not touch anything) =="
"$REPO/setup/install.sh" --dry-run
[ ! -e "$HOME/.claude/statusline.sh" ] || fail "dry-run seeded statusline.sh"
pass "dry-run made no changes"

echo "== install =="
"$REPO/setup/install.sh"

echo "== doctor: expect a healthy, fully-wired install (recall is the one expected warn) =="
doctor_out="$("$REPO/setup/doctor.sh")" || fail "doctor.sh reported a real FAIL (see output above)"
echo "$doctor_out"
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

echo "== doctor checks the recall venv where it actually lives (~/.recall/.venv, not the repo) =="
printf '%s\n' "$doctor_out" | grep -qF '.recall/.venv' \
  || fail "doctor.sh's recall venv check didn't reference ~/.recall/.venv"
printf '%s\n' "$doctor_out" | grep -qF 'tools/recall/.venv' \
  && fail "doctor.sh still checks the wrong path (repo's tools/recall/.venv can never exist)"
pass "doctor.sh recall venv check targets ~/.recall/.venv"

echo "== spot-check the wiring doctor is supposed to verify =="
[ -L "$HOME/.gemini/GEMINI.md" ] || fail "gemini not symlinked (mode=link)"
[ -L "$HOME/.config/opencode/AGENTS.md" ] || fail "opencode not symlinked (mode=link)"
grep -qF '# >>> agent-rules hub' "$HOME/.codex/AGENTS.md" || fail "codex block not written (mode=block)"
[ -L "$HOME/.claude/CLAUDE.md" ] || fail "claude CLAUDE.md -> AGENTS.md symlink missing"
grep -q "^@$REPO/core.md" "$HOME/.claude/AGENTS.md" || fail "claude AGENTS.md missing hub import"
[ -x "$HOME/.claude/statusline.sh" ] || fail "statusline.sh not seeded/executable"
[ -x "$HOME/.recall/recall.py" ] || fail ".recall/recall.py not seeded/executable"
[ -f "$HOME/.recall/config.example.json" ] || fail ".recall/config.example.json not seeded"
[ ! -x "$HOME/.recall/README.md" ] || fail ".recall/README.md wrongly made executable"
pass "hub wiring matches map"

for catalog in .agents .codex .claude; do
  [ "$(readlink "$HOME/$catalog/skills/handoff")" = "$REPO/workflows/handoff" ] \
    || fail "$catalog handoff workflow not linked"
  [ "$(readlink "$HOME/$catalog/skills/council")" = "$REPO/workflows/council" ] \
    || fail "$catalog council workflow not linked"
  [ "$(readlink "$HOME/$catalog/skills/wrap")" = "$HOME/.private/wrap" ] \
    || fail "$catalog private wrap override not linked"
done
[ -d "$HOME/.codex/skills/your-voice" ] && [ ! -L "$HOME/.codex/skills/your-voice" ] \
  || fail "real workflow destination was clobbered"
pass "workflow links match the effective map without clobbering real destinations"

[ "$(readlink "$HOME/.pi/agent/prompts/goal.md")" = "$REPO/prompts/goal.md" ] \
  || fail "identical real goal.md was not adopted as a link"
pass "identical real prompt file adopted as link"

echo "== prompt templates: differing real file is preserved and reported =="
rm "$HOME/.pi/agent/prompts/goal.md"
printf 'MY LOCAL GOAL\n' > "$HOME/.pi/agent/prompts/goal.md"
"$REPO/setup/install.sh" > "$WORK/divergent.log" 2>&1 || fail "install.sh failed on a divergent prompt file"
grep -q 'REFUSE: .*goal.md is a real file that differs' "$WORK/divergent.log" \
  || fail "divergent prompt file was not reported"
grep -q "MY LOCAL GOAL" "$HOME/.pi/agent/prompts/goal.md" || fail "divergent prompt file was clobbered"
[ ! -L "$HOME/.pi/agent/prompts/goal.md" ] || fail "divergent prompt file was replaced by a link"
rm "$HOME/.pi/agent/prompts/goal.md"
"$REPO/setup/install.sh" > /dev/null
[ "$(readlink "$HOME/.pi/agent/prompts/goal.md")" = "$REPO/prompts/goal.md" ] \
  || fail "fresh prompt link not created after the divergent file was moved aside"
pass "divergent prompt file preserved; fresh install links it"

echo "== doctor: reject a drifted or dangling prompt link and recover after repair =="
ln -sfn "$REPO/core.md" "$HOME/.pi/agent/prompts/goal.md"
if "$REPO/setup/doctor.sh" > /dev/null 2>&1; then fail "doctor accepted a wrong prompt link"; fi
ln -sfn "$REPO/prompts/does-not-exist.md" "$HOME/.pi/agent/prompts/goal.md"
if "$REPO/setup/doctor.sh" > /dev/null 2>&1; then fail "doctor accepted a dangling prompt link"; fi
"$REPO/setup/install.sh" > /dev/null
"$REPO/setup/doctor.sh" > /dev/null || fail "doctor remained unhealthy after prompt repair"
pass "doctor detects prompt-link drift and installer repairs it"

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

echo "== recall is seeded ONCE then left alone (must survive a re-run untouched) =="
printf '#!/usr/bin/env python3\n# MY CUSTOM RECALL EDIT\n' > "$HOME/.recall/recall.py"
"$REPO/setup/install.sh"
grep -q "MY CUSTOM RECALL EDIT" "$HOME/.recall/recall.py" \
  || fail "install.sh clobbered a local ~/.recall/recall.py edit"
pass ".recall divergence survives a re-run"

echo
echo "ALL FRESH-INSTALL CHECKS PASSED"
