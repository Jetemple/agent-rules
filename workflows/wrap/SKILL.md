---
name: wrap
description: Use at the END of a session to capture durable facts — "/wrap", "wrap up", "save what's useful from this session", "remember the important stuff before I go". Reflects on the conversation just had (already in context), dedups against existing memory, proposes the keepers, writes the approved ones. NOT for retrospective corpus mining or pruning existing memory (a consolidation pass).
---

# wrap

> **Assumes a recall-backed Markdown corpus.** Individual memory files are the source of truth;
> recall's database is a derived search cache. This workflow relies on a one-file-per-fact
> frontmatter contract (`name` / `description` / `metadata.type` / `originSessionId`) and a means
> of reindexing after a write. A `MEMORY.md` catalog is neither required nor maintained.

Session-end memory capture. The just-finished conversation is **already in your context** — no
transcript mining needed. You **reflect on the session you just lived through**, pull out the few
durable facts worth keeping, and write the approved ones.

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

**Be strict.** A high-quality miss beats a noisy hit. **Zero is the normal result** for routine
sessions. A long, unusually dense session might yield 1–3. More than 3 means the filter failed:
stop and narrow the list before proposing it.

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
For each candidate, check it isn't already captured by querying recall:
```sh
python3 ~/.recall/recall.py "the candidate fact in a few words" -k 3
```
If a near-match comes back `[V+K]`/`[V]` at #1, it's likely already covered — drop
it, or plan to *extend* that file rather than create a duplicate. Do not read or update a
`MEMORY.md` catalog for deduplication; recall searches the source files directly.

### 3. Propose before writing
Present a short table — **slug · type · one-line · target dir · new-or-extends** —
and for each, one line of *evidence* (the actual correction/decision, not your
inference). Flag any marginal entry (thin, or already implied by CLAUDE.md) and
recommend keep/drop. Ask the user to approve. **Honor their answer exactly** — never write
a dropped one, never silently add one they didn't approve. Approval authorizes a qualifying
memory write; it does not turn a repo-derived, transient, or otherwise excluded fact into a
durable one.

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
- Write only the individual source file. **Never create, append to, or maintain `MEMORY.md`.**
  recall indexes source files directly, so a second catalog duplicates content and grows stale.
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
