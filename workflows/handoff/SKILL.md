---
name: handoff
description: Use when the user says "hand this off", "write a handoff", "I'm running low on / out of context", "compact this for a new session", "continue in a fresh window", or is about to /clear and wants the next agent to pick up the work.
argument-hint: "What will the next session focus on?"
---

# Handoff

Write a handoff document so a fresh agent (Claude or Codex) can continue the work with no prior conversation. Save it to the OS temp dir, NOT the workspace.

## Where to write it

Save to `$TMPDIR` (macOS) with a deterministic, descriptive name:

```
${TMPDIR%/}/handoff-<short-slug>-<YYYY-MM-DD>.md
```

`<short-slug>` = a few kebab words naming the work (e.g. `agentic-setup-audit`). Echo the absolute path back to the user when done.

## Rules

- **Don't duplicate artifacts.** If something is already captured in a PRD, plan, ADR, issue/ticket, commit, diff, or design doc, reference it by path/URL — don't paste it.
- **Redact secrets.** No API keys, tokens, passwords, or PII. If a value leaked into files, say "redacted — see <location>", never the value.
- **Tailor to the next focus.** If the user passed an argument, treat it as what the next session is for and weight the doc toward that.
- **State reality.** What's done AND verified, what's done-but-unverified, what's blocked, what's an open decision. Don't imply more is finished than is.

## Section template (use these headings)

```markdown
# Handoff — <title>

**Date:** <YYYY-MM-DD>  ·  **Next session focus:** <from the argument, or "continue current work">

## Task / goal
One or two sentences: what we're trying to achieve overall.

## Current state
Where things stand right now, in plain language.

## Done (and verified)
- <change> — how it was verified (test/command/output)

## Open / next steps
- <concrete next action> (reference the file/ticket, not a retelling)

## Decisions made
- <decision> — why (so the next agent doesn't relitigate it)

## Open questions
- <decision that's genuinely the user's to make>

## Files & branches
- Key paths, branches, PRs, and any large artifacts referenced (by path/URL)

## How to verify / resume
- The command(s) or steps to confirm the work, or to pick it back up

## Suggested skills
- Skills the next agent should invoke for this work (name + one-line why)
```

Drop a section only if it would be genuinely empty. Keep each bullet tight — the next agent reads this cold.
