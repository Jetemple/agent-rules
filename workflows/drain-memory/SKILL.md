---
name: drain-memory
description: Use at any point when memories may have gone false — "drain my memory", "re-align memories", "what's stale in memory", "/drain-memory", "you're acting on something outdated", "these notes don't match reality anymore". Sweeps the recall memory corpus for facts that time has falsified — lifecycle-complete work still worded as in-flight, version-pinned references silently superseded, point-in-time snapshots that have decayed, and internal contradictions — and proposes drain (delete/archive) or refresh for each before touching anything. NOT for calibrating hooks or merging clusters (a consolidation pass) or for adding new facts (wrap / a corpus-mining workflow).
---

# drain-memory

> **Assumes a memory-corpus convention.** This workflow reads and edits a Markdown memory
> corpus queried by `recall` (see `docs/memory-and-recall.md` and `tools/recall/`). It relies
> on conventions that repo, not this skill, defines: a per-directory `MEMORY.md` index, a
> one-file-per-fact frontmatter contract (`name` / `description` / `metadata.type` /
> `originSessionId`), `[[wikilink]]` cross-references, and a derived index (`~/.recall/memory.db`)
> that is rebuilt from the corpus. Corpus roots come from `~/.recall/config.json` (`sources[].path`),
> so this workflow never hardcodes a directory. If your corpus uses different conventions, adapt
> the frontmatter and index steps to match.

Reconcile the memory corpus against **current reality**. This is the truth-checking member of
the memory-maintenance family; the others don't do this job:

- **wrap / a corpus-mining workflow** — *intake*: capture facts not yet written down.
- **a consolidation pass** — *calibration*: trim over-long index hooks, merge redundant
  clusters, fix broken links. It assumes the facts are still **true**.
- **drain-memory** — *truth reconciliation*: find facts that were true when written but time
  has since **falsified**, and drain or refresh them.

The failure this prevents: a memory says "TICKET-123 awaiting Thursday's deploy," written weeks
ago; recall surfaces it; the agent acts on shipped work as if it were still in flight. Stale
memory is worse than missing memory — it loads with the same authority as a current fact and is
confidently wrong.

## Core idea: propose, then drain

**Propose-only by default.** This workflow reads, reasons about staleness from each memory's own
content and age, and presents a verdict table. **Nothing is deleted or edited until the user
approves.** No external calls (issue trackers, VCS, network) unless the user explicitly asks to
verify a specific claim against a live source — the point is a fast, self-contained sweep the
corpus can answer about itself.

Four verdicts per suspect:
- **DRAIN** — the fact is dead. Lifecycle complete, superseded, or falsified. Delete the file
  and its index line. (Or **ARCHIVE** if a paper trail is wanted — move it out of the corpus
  roots instead of deleting; see step 5.)
- **REFRESH** — still about a live thing, but the stated *state* is stale. Rewrite the state,
  re-stamp the date, keep the file.
- **VERIFY** — can't be adjudicated from the corpus alone. A suspect the user (or an explicit
  live-check pass) must confirm — never a unilateral drain.
- **KEEP** — false alarm. Timeless fact, or a situational memory whose reader will already know
  the state when they look. Say so and move on.

## What "stale" looks like (suspect signatures)

Hunt for these. Most are visible in the frontmatter + first paragraph — you rarely need the
whole file.

1. **Lifecycle-complete, still worded live.** `project` memories about work whose name or body
   says `in_flight`, `wip`, `awaiting`, `pending`, "current state (DATE)", "in progress",
   "Thursday deploy". If the dated state is weeks old, the work almost certainly moved on.

2. **Version-pinned references.** `reference` memories that pin a version — `*_v2`, `_v0139`,
   "as of X.Y.Z", "current IDs", "latest limits". These silently go wrong when upstream bumps.
   Flag for a freshness check; don't assume dead.

3. **Point-in-time snapshots.** Backlogs, sprint states, "in-flight" scouts, "current" anything.
   Decay by construction.

4. **Internal contradictions.** Two memories giving different answers to the same question (two
   values for one limit, two "current" IDs). At most one is current. Surface the pair; file mtime
   is the recency tiebreaker (`originSessionId` is an opaque session UUID, **not** chronological —
   don't order by it), but confirm before draining the loser.

5. **Superseded by a live always-on rule.** A memory that duplicates something now in an
   always-loaded instruction file (`core.md`, a project `AGENTS.md`/`CLAUDE.md`, a skill). If the
   always-on rule is authoritative and current, the memory is dead weight.

6. **Resolved incidents / one-time fixes** worded as ongoing (`*_incident_*`, "fix in flight").
   Once shipped, drain, or refresh to a terse "resolved DATE" breadcrumb.

**Not stale** (leave alone): timeless domain facts (a schema shape, a naming convention, how a
subsystem works), reflexive rules (no attribution, confirm before push), and deep/situational
references where the reader learns the current value *when they arrive* at the situation. Age
alone is not staleness — it is a suspect signal for *stateful* memories only.

## Procedure

### 1. Enumerate the corpus with age + suspect signals
Read the corpus roots from recall's config so this stays tool-agnostic (leading-dash dirnames
break `basename` — parse paths in Python):

```sh
python3 - <<'PY'
import os, re, json, time
now = time.time()
cfg = os.path.expanduser('~/.recall/config.json')
sources = json.load(open(cfg)).get('sources', []) if os.path.exists(cfg) else []
# recall enumerates with os.walk and prunes EXCLUDE_DIRS (_archive, _scratch, .git, …);
# walk it the same way so this list matches exactly what recall indexes.
EXCLUDE = {"_scratch", "_archive", ".git", "node_modules", ".obsidian"}
for s in sources:
    label = s.get('label') or os.path.basename(s.get('path', ''))  # label disambiguates same-named roots
    root = os.path.expanduser(s.get('path', ''))
    if not os.path.isdir(root):
        continue
    for dp, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        for b in sorted(f for f in files if f.endswith('.md')):
            if b == 'MEMORY.md':
                continue
            f = os.path.join(dp, b)
            age = int((now - os.path.getmtime(f)) / 86400)
            txt = open(f, errors='replace').read()
            sig = []
            if re.search(r'in[_-]?flight|_ft_state|_slice\d|_incident|_leak|_wip', b, re.I):
                sig.append('lifecycle')
            if re.search(r'_v\d|v\d{3,}', b):
                sig.append('version-pinned')
            if re.search(r'awaiting|pending|in progress|current state|in flight|as of \d', txt, re.I):
                sig.append('live-wording')
            tag = ('  <-- ' + ','.join(sig)) if sig else ''
            print(f"{age:5d}d  [{label}] {b}{tag}")
PY
```

The `<-- ` tags are your first-pass suspect list; the age column shows how long a "current
state" has had to rot. The `live-wording` net is deliberately broad — step 2 triages most of it
to KEEP. The high-confidence tags are `lifecycle` and `version-pinned`. Reading roots and their
`label`s from `~/.recall/config.json` keeps this tool-agnostic and disambiguates roots whose
directories share a basename (e.g. several `…/memory` dirs).

### 2. Triage the suspects
For each tagged (or suspiciously old stateful) file, read only the frontmatter + first
paragraph. Assign DRAIN / REFRESH / VERIFY / KEEP from the memory's own content and age. Do
**not** open live sources unless the user asked.

### 3. Cross-check for contradictions
Group suspects by topic. Where two memories answer the same question differently, list the pair,
mark the likely-current one (newer file mtime, or the value that agrees with other current
memories — not `originSessionId`, which is a non-chronological UUID), and propose draining or
merging the stale one. This is the one place you may need to read both files in full.

### 4. Propose before draining
Present a table grouped by corpus root:

| file · root | age | signature | verdict | one-line reason |
|---|---|---|---|---|

DRAIN rows first, then REFRESH, then VERIFY, then a short "checked, KEEP" count so the user sees
the sweep was real. Every DRAIN needs its one-line reason it's dead; every REFRESH shows the
proposed new state line. **Get the user's approval and honor it exactly — never drain a VERIFY or
a KEEP.**

### 5. Apply the approved changes (from a real interactive session — never a subagent)
- **DRAIN → delete:** remove the file and its `MEMORY.md` index line. First grep the corpus for
  inbound `[[wikilinks]]` to it and repoint or drop them (a dangling link is exactly what a
  consolidation pass hunts for). Because the recall index (`~/.recall/memory.db`) is **derived**,
  the fact only disappears from search after you reindex (step 6) — deleting the `.md` alone
  leaves it in the SQLite/FTS index until rebuilt. recall's reindex does purge files that have
  disappeared (it drops any indexed path no longer seen on the walk), so a plain `rm` + reindex is
  a complete delete.
- **DRAIN → archive:** recall walks each root recursively but **prunes a fixed set of directory
  names** (`_archive`, `_scratch`, `.git`, `node_modules`, `.obsidian`). So the zero-config archive
  move is `mkdir -p <root>/_archive && mv <file> <root>/_archive/` — the file stays on disk for the
  paper trail but drops out of the index on the next reindex. (Confirm the excluded-dir set against
  your `tools/recall/` version; if yours doesn't prune `_archive`, move the file to a directory
  that is not a configured `sources[].path` instead.) Then remove its `MEMORY.md` index line.
- **REFRESH → edit:** rewrite the stale state, update the "current state (DATE)" stamp, keep
  frontmatter and `originSessionId`. Preserve the `**Why:**` / `**How to apply:**` lines for
  feedback/project memories.

### 6. Reindex and verify the drain took
recall's index is derived and must be rebuilt after any delete/edit. If the optional `PostToolUse`
reindex hook is wired (see `tools/recall/README.md`) it fires on `memory/*.md` writes, but a
**delete** may not trigger it — rebuild explicitly (incremental; only changed/removed files are
touched, and vanished files are purged):

```sh
python3 tools/recall/recall.py index      # or your installed entrypoint (e.g. ~/.recall/recall.py)
python3 tools/recall/recall.py stats
```

Then **prove the drained record is actually gone**, not merely outranked — a rank/count delta
alone doesn't confirm removal (a near-duplicate could fill the slot). Query and confirm the
drained file's *path* no longer appears in the results:

```sh
python3 tools/recall/recall.py "the stale claim you just drained" -k 5   # its path must be absent
```

Confirm the file count dropped by the number drained, the index line count moved to match, and no
dangling `[[links]]` remain. Report a before/after (files, index lines, what drained / refreshed /
verify-pending) and the honest verdict — often "3 drained, 2 refreshed, corpus otherwise current"
is the whole story.

> Path note: examples use `tools/recall/recall.py` (the repo path). On an installed machine the
> entrypoint may live elsewhere (e.g. `~/.recall/recall.py`); use whichever your setup exposes —
> they're the same script.

## Rules
- **Propose before draining. Always.** Deletion is the destructive end of the memory lifecycle;
  it gets a look every time. The corpus is typically **not** version-controlled — a deleted
  memory is gone unless archived. When in doubt, ARCHIVE over DELETE.
- **The corpus judges itself.** No live tracker/VCS/network calls unless the user explicitly asks
  to verify a named claim. Uncertain-from-content → VERIFY, not DRAIN.
- **Don't drain timeless facts for being old.** Age is a suspect signal for *stateful* memories
  only.
- **Never drain from a subagent run.** Subagents may *propose* across the corpus; the interactive
  session applies after approval (same rule as any corpus-mining workflow).
- **Repoint links before deleting.** A drain that leaves a dangling `[[wikilink]]` just moved the
  mess.
- **The index is derived — reindex after every drain/refresh.** Deleting a `.md` without
  rebuilding `~/.recall/memory.db` leaves the stale fact searchable.
- **Don't write a memory *about* having drained** — that's conversation-scoped.
- If the index crossed its size budget or clusters need merging, that's a consolidation pass —
  hand off, don't do it here.

## Relationship to sibling workflows
Drain is the truth-checking cousin of the consolidation pass: consolidation fixes a fact's
*shape* (assuming it's current); drain checks whether it's still *true*. A healthy cadence:
**wrap** (per session) → **corpus-mining** (retrospective intake) → **drain-memory** (kill the
false) → **consolidation** (calibrate what remains).
