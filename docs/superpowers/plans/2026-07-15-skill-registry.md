# Skill Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register public and privately overridden workflow skills reproducibly across shared, Codex, and Claude skill catalogs.

**Architecture:** A declarative `workflow-map` names public workflows and targets. A sourced Bash module resolves an optional private map over the public map and supplies identical entries to the installer and doctor.

**Tech Stack:** macOS-compatible Bash 3.2, POSIX `awk`, filesystem symlinks, shell smoke tests.

## Global Constraints

- Keep private and project-specific skill sources outside this public repository.
- Never publish machine-specific absolute paths.
- Refuse to overwrite user-owned files or directories.
- Support `agents`, `codex`, and `claude` targets.
- Do not commit until the user confirms the repository, branch, action, and intended diff.

---

### Task 1: Resolve Public Workflows and Private Overrides

**Files:**
- Create: `workflow-map`
- Create: `setup/workflows.sh`
- Create: `setup/test-workflows.sh`

**Interfaces:**
- Consumes: `$REPO/workflow-map` and optional `${XDG_CONFIG_HOME:-$HOME/.config}/agent-rules/workflow-map`.
- Produces: `workflow_entries`, `workflow_source`, and `workflow_catalog` shell functions.

- [ ] **Step 1: Write the failing resolver test**

Create an isolated temporary repository and home. Assert public order, private replacement of `wrap`, appending a private-only skill, leading-tilde expansion, and all three catalog mappings:

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO_SRC="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
REPO="$WORK/repo"; HOME="$WORK/home"; export HOME
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
[ "$(workflow_source "$REPO" private '~/.private/wrap')" = "$HOME/.private/wrap" ]
[ "$(workflow_catalog agents)" = "$HOME/.agents/skills" ]
[ "$(workflow_catalog codex)" = "$HOME/.codex/skills" ]
[ "$(workflow_catalog claude)" = "$HOME/.claude/skills" ]
```

- [ ] **Step 2: Run the resolver test and verify RED**

Run: `bash setup/test-workflows.sh`

Expected: failure because `setup/workflows.sh` does not exist.

- [ ] **Step 3: Add the public registry**

Create `workflow-map`:

```text
# name      source                    targets
handoff     workflows/handoff         agents,codex,claude
wrap        workflows/wrap            agents,codex,claude
your-voice  workflows/your-voice      agents,codex,claude
```

- [ ] **Step 4: Implement the minimal resolver**

Create `setup/workflows.sh`. Use POSIX `awk` arrays to retain public order, overlay private records by workflow name, append private-only records, reject records whose field count is not three, and emit `origin name source targets`. Implement catalog mapping with a `case` statement and resolve only leading `~` in private sources.

```bash
workflow_private_map() {
  printf '%s/agent-rules/workflow-map' "${XDG_CONFIG_HOME:-$HOME/.config}"
}

workflow_source() {
  local repo="$1" origin="$2" source="$3"
  if [ "$origin" = public ]; then printf '%s/%s' "$repo" "$source"
  else printf '%s' "${source/#\~/$HOME}"
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
```

- [ ] **Step 5: Run the resolver test and verify GREEN**

Run: `bash setup/test-workflows.sh`

Expected: exit 0 with no output.

- [ ] **Step 6: Pause before any commit**

Show the Task 1 diff. Do not commit without explicit approval for the known repository, branch, action, and diff.

### Task 2: Install Workflow Links Without Clobbering

**Files:**
- Modify: `setup/test-fresh-install.sh`
- Modify: `setup/install.sh`

**Interfaces:**
- Consumes: Task 1 resolver functions and existing `link <source> <destination>`.
- Produces: declared catalog symlinks; preserves real destinations and selected source directories.

- [ ] **Step 1: Add failing fresh-install assertions**

Create a private wrapper and override map inside the test home. Pre-create a real `your-voice` directory. After installation, assert public `handoff` and private `wrap` links in all catalogs and assert the real directory survived:

```bash
mkdir -p "$HOME/.private/wrap" "$HOME/.config/agent-rules" "$HOME/.codex/skills/your-voice"
printf '%s\n' 'wrap ~/.private/wrap agents,codex,claude' \
  > "$HOME/.config/agent-rules/workflow-map"

for catalog in .agents .codex .claude; do
  [ "$(readlink "$HOME/$catalog/skills/handoff")" = "$REPO/workflows/handoff" ] \
    || fail "$catalog handoff workflow not linked"
  [ "$(readlink "$HOME/$catalog/skills/wrap")" = "$HOME/.private/wrap" ] \
    || fail "$catalog private wrap override not linked"
done
[ -d "$HOME/.codex/skills/your-voice" ] && [ ! -L "$HOME/.codex/skills/your-voice" ] \
  || fail "real workflow destination was clobbered"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `bash setup/test-fresh-install.sh`

Expected: failure at the first workflow-link assertion.

- [ ] **Step 3: Install effective workflow entries**

Source `setup/workflows.sh`. Iterate `workflow_entries "$REPO"`, resolve the source, require a source directory, split comma-separated targets under Bash 3.2, skip a destination whose physical path is the selected source, and invoke the existing `link` helper otherwise:

```bash
. "$REPO/setup/workflows.sh"

while read -r origin name source targets; do
  [ -n "$origin" ] || continue
  src="$(workflow_source "$REPO" "$origin" "$source")"
  [ -d "$src" ] || { echo "REFUSE: workflow '$name' source missing: $src" >&2; continue; }
  old_ifs="$IFS"; IFS=,; set -- $targets; IFS="$old_ifs"
  for target in "$@"; do
    catalog="$(workflow_catalog "$target")" || {
      echo "REFUSE: workflow '$name' has unknown target '$target'" >&2; continue
    }
    dest="$catalog/$name"
    if [ -d "$dest" ] && [ "$(cd "$src" && pwd -P)" = "$(cd "$dest" && pwd -P)" ]; then
      echo "ok (source directory): $dest"
    else
      link "$src" "$dest"
    fi
  done
done <<EOF
$(workflow_entries "$REPO")
EOF
```

- [ ] **Step 4: Run installation tests and verify GREEN**

Run: `bash setup/test-workflows.sh && bash setup/test-fresh-install.sh`

Expected: resolver exits 0; fresh-install test ends with `ALL FRESH-INSTALL CHECKS PASSED`. The deliberate real-directory collision is reported and preserved.

- [ ] **Step 5: Pause before any commit**

Show the Task 2 diff and verification. Do not commit without explicit approval.

### Task 3: Diagnose Drift and Document the Registry

**Files:**
- Modify: `setup/test-fresh-install.sh`
- Modify: `setup/doctor.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: the effective registry and installed link layout.
- Produces: health results for every declared skill registration and public usage documentation.

- [ ] **Step 1: Add a failing doctor drift test**

After the healthy doctor pass, point one shared `wrap` link at the wrong source and require doctor to fail. Re-run the installer and require doctor to recover:

```bash
ln -sfn "$REPO/workflows/wrap" "$HOME/.agents/skills/wrap"
if "$REPO/setup/doctor.sh"; then fail "doctor accepted an incorrect workflow link"; fi
"$REPO/setup/install.sh"
"$REPO/setup/doctor.sh" || fail "doctor remained unhealthy after repair"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `bash setup/test-fresh-install.sh`

Expected: `FAIL: doctor accepted an incorrect workflow link`.

- [ ] **Step 3: Verify effective entries in doctor**

Source `setup/workflows.sh` after `check_link` is defined. Iterate identically to the installer. Set `fail=1` for absent sources, invalid targets, and incorrect links. Let `check_link` classify absent or real destinations as not installed. Accept a real directory only when it is the selected source directory.

```bash
while read -r origin name source targets; do
  [ -n "$origin" ] || continue
  src="$(workflow_source "$REPO" "$origin" "$source")"
  [ -d "$src" ] || { echo "FAIL: workflow '$name' source missing: $src"; fail=1; continue; }
  old_ifs="$IFS"; IFS=,; set -- $targets; IFS="$old_ifs"
  for target in "$@"; do
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
done <<EOF
$(workflow_entries "$REPO")
EOF
```

- [ ] **Step 4: Document public and private maps**

Update `README.md` to list `workflow-map`, explain that the installer registers skills, and show only this generic private override example:

```text
wrap ~/.private/wrap agents,codex,claude
```

- [ ] **Step 5: Run full verification**

Run:

```bash
bash -n setup/install.sh setup/doctor.sh setup/workflows.sh setup/test-workflows.sh setup/test-fresh-install.sh
bash setup/test-workflows.sh
bash setup/test-fresh-install.sh
./check-privacy.sh
git diff --check
```

Expected: syntax and resolver checks exit 0; fresh install ends with `ALL FRESH-INSTALL CHECKS PASSED`; privacy and diff checks exit 0.

- [ ] **Step 6: Pause before any commit**

Show the full intended diff, current branch, and verification output. Do not commit or push without explicit approval.

### Task 4: Apply the Private Wrapper Override Locally

**Files:**
- Create or modify outside the repository: `${XDG_CONFIG_HOME:-$HOME/.config}/agent-rules/workflow-map`

**Interfaces:**
- Consumes: the existing private wrapper directory.
- Produces: shared and Codex `wrap` links to that private source; leaves the Claude source intact.

- [ ] **Step 1: Inspect source and current private map**

Run `test -d "$HOME/.claude/skills/wrap"` and inspect the private map if it exists.

- [ ] **Step 2: Add one surgical override**

Preserve unrelated entries and ensure exactly one active line:

```text
wrap ~/.claude/skills/wrap agents,codex
```

- [ ] **Step 3: Preview, install, and diagnose**

Run:

```bash
./setup/install.sh --dry-run
./setup/install.sh
./setup/doctor.sh
```

Expected: shared and Codex links resolve to the existing private Claude wrapper. A fresh Codex session is required for session-start discovery.

- [ ] **Step 4: Verify links directly**

Run:

```bash
test "$(readlink "$HOME/.agents/skills/wrap")" = "$HOME/.claude/skills/wrap"
test "$(readlink "$HOME/.codex/skills/wrap")" = "$HOME/.claude/skills/wrap"
```

Expected: both commands exit 0. The private map is outside the repository and is not committed.
