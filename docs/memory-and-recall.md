# Memory & recall

`tools/recall` is a semantic search CLI over a Markdown **memory corpus** — a directory of
notes an agent accumulates across sessions (decisions, gotchas, how-tos). It ranks by meaning,
not just keywords, so an agent can ask a natural-language question and get the relevant notes
back without knowing which file they live in.

## Querying

```sh
python3 tools/recall/recall.py "how do I rebuild the index"
```

It returns ranked `path:line` snippets. Open the full file only when a snippet is insufficient.
Use recall for "I don't know which file holds the answer" lookups — skip it when a plain `rg`
or an already-known fact answers the question.

## How ranking works

- Embeddings come from the Ollama model **`embeddinggemma:300m`** (pull it per `docs/setup.md`).
- Default ranking is vector-only. On a short, semantically-distinct corpus that beats hybrid
  keyword fusion; pass `--hybrid` to restore RRF fusion for larger/noisier corpora.
- **Graceful degradation:** if Ollama is down or unreachable, recall falls back to keyword-only
  (FTS) results instead of crashing. Keyword-only results are tagged so you know embeddings
  were skipped.

## The index is derived — never commit it

`~/.recall/memory.db` is a **derived** SQLite/FTS index built from the corpus. You build it
explicitly with `python3 tools/recall/recall.py index` — it does **not** auto-build on the
first query, so an un-indexed corpus returns `(no matches)`. Re-runs are incremental (only
changed files re-embed). It is gitignored and must never be committed — it is rebuilt locally,
per machine. Only the corpus Markdown, the code, and `*.example.json` config are tracked.

Config is read from `~/.recall/config.json` (the code looks there, not in the repo). Copy
`config.example.json` to `~/.recall/config.json` and point it at your machine's corpus path
(see `docs/setup.md` for the full bootstrap).

## Draining stale memory (truth reconciliation)

A memory corpus doesn't only grow and need tidying — it also **goes false**. A note that was
true when written ("TICKET-123 awaiting Thursday's deploy") becomes confidently wrong once the
work ships, yet recall surfaces it with the same authority as a current fact. Stale memory is
worse than missing memory.

Three distinct maintenance jobs, all against the same corpus:

- **Intake** (wrap / a corpus-mining workflow) — capture facts not yet written down.
- **Consolidation** — calibrate index hooks, merge redundant clusters, fix broken `[[links]]`.
  Assumes the facts are still *true*.
- **Draining** (`workflows/drain-memory`) — reconcile against current reality: find facts time
  has *falsified* (lifecycle-complete work worded as in-flight, version-pinned references
  silently superseded, point-in-time snapshots, internal contradictions) and delete/archive or
  refresh them.

Because the recall index (`~/.recall/memory.db`) is **derived**, a drain isn't complete until you
reindex — deleting a corpus `.md` alone leaves the stale fact in the SQLite/FTS index until
`python3 tools/recall/recall.py index` rebuilds it (the reindex also purges files that have
disappeared from the walk). Draining is propose-only by default: it reasons from the corpus's own
content and never calls a live tracker unless asked.
