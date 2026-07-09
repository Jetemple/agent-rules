---
name: wrap
description: Use at the END of a session to capture durable facts worth remembering — "/wrap", "wrap up", "save what's useful from this session", "remember the important stuff before I go". Reflects on the conversation just had (it's already in context), dedups against existing memory, proposes the keepers, and writes the approved ones. NOT for mining the whole transcript corpus retrospectively (that's a job for a separate corpus-mining workflow) or pruning what already exists (that's a separate consolidation pass).
---

# wrap

> **Assumes a memory-corpus convention.** This workflow writes into a Markdown memory corpus
> queried by `recall` (see `docs/memory-and-recall.md` and `tools/recall/`). It relies on a few
> conventions that repo, not this skill, defines: a per-directory `MEMORY.md` index, a one-file-
> per-fact frontmatter contract (`name` / `description` / `metadata.type` / `originSessionId`),
> and a means of reindexing after a write. Set recall up first; if your corpus uses different
> conventions, adapt the frontmatter and index steps below to match it.

Session-end memory capture. The just-finished conversation is **already in your
context** — so unlike a retrospective corpus-mining workflow (which fans reader agents
over the whole transcript corpus), `/wrap` needs no Workflow and no transcript mining. You simply
**reflect on the session you just lived through**, pull out the few durable facts
worth keeping, and write the approved ones. It's the lightweight, single-session,
in-the-moment counterpart to backfill.

## The one job: separate durable from conversational

Most of any session is conversation-scoped and should evaporate. You are hunting
for the small number of facts that will matter in a **future, unrelated session**:

- **Corrections** the user gave you ("no, don't…", "actually…", "stop", "I told you…")
  → almost always a `feedback` memory. Capture the rule *and the why*.
- **Decisions + their rationale** ("let's do X instead of Y because…") → `feedback`
  or `project`.
- **Recurring friction / gotchas** you hit and solved (env quirks, tool flags,
  failure modes, a non-obvious fix) → `reference` or `feedback`.
- **Project-state conclusions** ("X is shipped", "Y is blocked on Z", a design
  locked in) → `project`. Convert relative dates to absolute.
- **Identity / preference statements** about the user or how they want you to work →
  `user` or `feedback`.
- **Pointers to external resources** discovered this session (a dashboard, ticket,
  doc, CLI) → `reference`.

**Be strict.** A high-quality miss beats a noisy hit. A short, focused session may
yield **zero** — that's a perfectly good `/wrap` result. A long, dense one might
yield 2–4. Rarely more.

### Exclude (do NOT write)
- Anything already in memory (dedup — see step 2).
- Anything derivable from CLAUDE.md / AGENTS.md / the repo / git history.
- Step-by-step detail of *this* task that won't recur.
- A memory *about* having run this session or this `/wrap`.
- Speculation or your own inference — only facts the user confirmed, corrected, or
  decided. If you're tempted to write something they didn't actually endorse, drop it.
- PR/build lifecycle status — opened, pushed, review comment addressed, build
  passed, commit hash. Your VCS's PR-inspect commands (e.g. `gh pr view`) and git are always
  fresher than a memory snapshot. This applies even when the candidate would
  just *extend* an existing project file — extending isn't exempt from the
  durability filter (see step 3).

## Procedure

### 1. Reflect over the session (from context — don't re-read the transcript)
Scan the conversation in your context window for the signal categories above.
Jot a raw candidate list. If the session was compacted and you've lost the early
part, you may read the **tail** of the current transcript to recover it, but the
in-context summary is usually enough — don't burn tokens re-paging what you remember.

### 2. Dedup against existing memory
For each candidate, check it isn't already captured. Fast path — query recall and
skim the index:
```sh
python3 ~/.recall/recall.py "the candidate fact in a few words" -k 3
```
If a near-match comes back `[V+K]`/`[V]` at #1, it's likely already covered — drop
it, or plan to *extend* that file rather than create a duplicate. Also glance at the
relevant `MEMORY.md` section for the target dir.

### 3. Propose before writing
Present a short table — **slug · type · one-line · target dir · new-or-extends** —
and for each, one line of *evidence* (the actual correction/decision, not your
inference). Flag any marginal entry (thin, or already implied by CLAUDE.md) and
recommend keep/drop. Ask the user to approve. **Honor their answer exactly** — never write
a dropped one, never silently add one they didn't approve.

"Extends an existing file" is not its own justification — a candidate that would
just append a status update (PR pushed, comment fixed, build green) to an existing
project file still has to clear the durability bar on its own merits. If the only
reason to write it is "there's already a file for this ticket," drop it.

### 4. Write the approved memories (this session writes — that's the whole point)
`/wrap` runs in a **real interactive session**, so writing here is correct and
in-discipline (the "never persist from a throwaway/subagent run" rule is about
`codex exec`/subagents, not this). One file per fact, following the contract:
- Filename matches the `name:` slug.
- Frontmatter: `name`, `description` (the retrieval hook — make it **distinctive**
  vs siblings or it collides in recall), `metadata.type`
  (`user|feedback|project|reference`), and `originSessionId` (this session's id).
- `feedback`/`project` bodies end with `**Why:**` and `**How to apply:**` lines.
- Link related memories with `[[name]]` (cross-dir links are fine; a link to a
  not-yet-written memory is OK — it marks one worth writing).
- Pick the memory dir that matches the current project (the matching project dir for
  project-specific facts, global for cross-project facts).
- Add the one-line pointer to that dir's `MEMORY.md` under the right section
  (`- [Title](file.md) — hook`). Never put memory *content* in MEMORY.md.
- To extend rather than duplicate, `Edit` the existing file instead.

### 5. Reindex, then spot-check
recall's index is derived and must be refreshed after a write. If you've wired the optional
`PostToolUse` reindex hook (see `tools/recall/README.md`), it runs automatically on every
`memory/*.md` write; otherwise run `python3 ~/.recall/recall.py index` yourself (it's
incremental). Then confirm one new memory is retrievable:
```sh
python3 ~/.recall/recall.py "a question the new memory should answer" -k 2
```
It should rank #1. If it loses to a sibling, **sharpen its `description:`** — the
highest-leverage fix (moves colliders back to #1 without touching the ranker).

## Rules
- Strict filter — quality over quantity; **zero memories is a valid wrap.**
- Propose → approve → write. Never write an unapproved fact; never skip a confirmed one.
- One fact per file. Frontmatter + `**Why:**`/`**How to apply:**` for feedback/project.
- Don't save what CLAUDE.md / AGENTS.md / the repo / git already record, or what only
  mattered to this conversation.
- Don't write a memory about having wrapped.
- Distinctive `description:` fields are not optional — recall ranks by them.
- If a fact is large or spans many sessions, hand off to a corpus-mining workflow
  or a consolidation pass instead of cramming it here.
