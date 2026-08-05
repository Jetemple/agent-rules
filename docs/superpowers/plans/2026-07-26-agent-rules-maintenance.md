# Agent Rules Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Update and repair the agent-rules hub while preserving local-only recall behavior.

**Architecture:** Fast-forward the public hub, enforce the compaction documentation
contract with a focused shell test, keep shared continuity behavior in `core.md`, and
use the existing installer/doctor as the source of truth for deployed wiring.

**Tech Stack:** POSIX shell, JSON, Markdown, Git, Claude Code settings, Codex TOML.

## Global Constraints

- Preserve all pre-existing uncommitted changes.
- Do not overwrite `~/.recall/recall.py`.
- Use recoverable moves for user-owned files.
- Do not commit, push, merge, create/update a PR, or release without a separate
  explicit confirmation naming the action.
- Keep the public repository free of personal paths and identity.

---

### Task 1: Update the checkout

**Files:**
- Preserve: `core.md`
- Receive from upstream: installer, doctor, recall documentation, workflow registry,
  and `workflows/drain-memory/SKILL.md`

**Interfaces:**
- Consumes: local `main` at `0a012de`, remote `main` at `f11d76f`
- Produces: a fast-forwarded checkout with the local `core.md` diff intact

- [ ] **Step 1: Record the current diff and personalized recall checksum**

Run:

```sh
git status --short --branch
git diff -- core.md
shasum ~/.recall/recall.py
```

- [ ] **Step 2: Fast-forward without merging**

Run:

```sh
git pull --ff-only
```

Expected: two commits are applied and `core.md` remains modified.

- [ ] **Step 3: Recheck preserved state**

Run:

```sh
git status --short --branch
git diff -- core.md
shasum ~/.recall/recall.py
```

Expected: the checksum is unchanged and the local rule remains present.

### Task 2: Lock the 200k compaction contract

**Files:**
- Create: `setup/test-compaction-config.sh`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/compaction.md`
- Modify: `setup/settings.example.json`
- Modify: `core.md`

**Interfaces:**
- Consumes: Claude's `env` settings object and Codex's
  `model_auto_compact_token_limit`
- Produces: executable test coverage and consistent 200k examples

- [ ] **Step 1: Write the failing test**

The test must validate JSON syntax, `autoCompactEnabled`, Claude's documented
`CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000`, the optional 100% override, Codex's
200000 limit, and the presence of the compaction-continuity rule. CI must run the
test and include it in shellcheck.

- [ ] **Step 2: Run the test and verify the expected failure**

Run:

```sh
bash setup/test-compaction-config.sh
```

Expected: failure because the checked-in examples still use 150000 and `core.md`
lacks the continuity rule.

- [ ] **Step 3: Make the minimal documentation/config changes**

Use an `env` block in `setup/settings.example.json`; explain that the effective
window is capped by the model window and is distinct from the exact trigger shown
by `/context`. Keep the continuity rule short and tool-agnostic.

- [ ] **Step 4: Run the focused test**

Run:

```sh
bash setup/test-compaction-config.sh
```

Expected: `PASS: compaction config and continuity guidance`.

### Task 3: Repair installed wiring

**Files:**
- Move: `~/.claude/skills/handoff` to
  `~/.claude/skills/handoff.pre-agent-rules-20260726`
- Generate through installer: `~/.claude/skills/handoff`
- Refresh through installer: `~/.codex/AGENTS.md`

**Interfaces:**
- Consumes: `workflow-map`, `core.md`, `setup/install.sh`
- Produces: registry-managed workflow links and a current Codex managed block

- [ ] **Step 1: Verify the duplicate content still matches**

Run:

```sh
diff -qr ~/.claude/skills/handoff workflows/handoff
```

Expected: no differences.

- [ ] **Step 2: Move the real directory to a recoverable backup**

Run:

```sh
mv ~/.claude/skills/handoff ~/.claude/skills/handoff.pre-agent-rules-20260726
```

- [ ] **Step 3: Preview and apply the installer**

Run:

```sh
./setup/install.sh --dry-run
./setup/install.sh
```

- [ ] **Step 4: Verify the resulting link**

Run:

```sh
readlink ~/.claude/skills/handoff
```

Expected: it resolves to this checkout's `workflows/handoff`.

### Task 4: Verify the system

**Files:**
- Verify only; no additional production changes

**Interfaces:**
- Consumes: the updated checkout and installed configuration
- Produces: fresh evidence for tests, privacy, doctor, and recall behavior

- [ ] **Step 1: Run repository tests**

Run:

```sh
bash setup/test-compaction-config.sh
bash setup/test-workflows.sh
bash setup/test-fresh-install.sh
```

Expected: all pass.

- [ ] **Step 2: Run privacy checks**

Run:

```sh
./check-privacy.sh
```

Expected: pass.

- [ ] **Step 3: Run doctor**

Run:

```sh
./setup/doctor.sh
```

Expected: no `FAIL` entries.

- [ ] **Step 4: Verify recall preservation and availability**

Run:

```sh
shasum ~/.recall/recall.py
python3 ~/.recall/recall.py "compaction continuity"
```

Expected: the pre-update checksum is unchanged; semantic results are returned when
Ollama is running, otherwise the keyword fallback is reported honestly.

- [ ] **Step 5: Review the final diff and stop before version-control writes**

Run:

```sh
git status --short --branch
git diff --check
git diff --stat
git diff
```

Report the diff and verification evidence. Request confirmation before any commit or
push.
