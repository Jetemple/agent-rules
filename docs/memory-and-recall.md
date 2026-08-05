# Memory & recall

`tools/recall` is a semantic search CLI over a Markdown **memory corpus** — notes an agent
accumulates across sessions (decisions, gotchas, how-tos). It ranks by meaning, not just
keywords, so a natural-language question returns the relevant notes even when you don't know
which file they live in. Usage, the `[V]`/`[K]` result tags, and benchmarks live in
`tools/recall/README.md`; this page covers setup and maintenance.

## Querying

```sh
python3 tools/recall/recall.py "how do I rebuild the index"
```

Returns ranked `path:line` snippets. Open the full file only when a snippet is insufficient.
Use it for "I don't know which file" lookups — skip it when a plain `rg` or an already-known
fact answers.

## Setup

`install.sh` seeds `~/.recall/recall.py` once (`copy_once`); it then diverges per-device, so
repo updates don't auto-propagate — re-copy by hand if you want a repo-side fix. The venv +
config + first-index bootstrap lives in `docs/setup.md` §3 — one place, don't duplicate it.

Config is read from `~/.recall/config.json`, not the repo. The index (`~/.recall/memory.db`)
is a **derived** SQLite/FTS cache — never commit it. Re-runs are incremental (only changed
files re-embed) and purge files that have disappeared from the corpus.

## Draining stale memory

A memory corpus also goes **false**: a note true when written ("TICKET-123 awaiting
Thursday's deploy") stays confidently wrong after the work ships, yet recall surfaces it with
the same authority as a current fact. Stale memory is worse than missing memory.

Three jobs against the same corpus:

- **Intake** (wrap / a corpus-mining workflow) — capture facts not yet written down.
- **Consolidation** — calibrate index hooks, merge redundant clusters, fix broken `[[links]]`.
- **Draining** (`workflows/drain-memory`) — reconcile against current reality: find facts time
  has falsified (lifecycle-complete work worded as in-flight, superseded version pins,
  point-in-time snapshots, internal contradictions) and delete/archive or refresh them.

Because the index is derived, a drain isn't complete until you reindex — deleting a corpus
`.md` alone leaves the stale fact retrievable. Draining is propose-only by default: it reasons
from the corpus's own content and never calls a live tracker unless asked.
