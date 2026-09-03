# recall

A tool-agnostic **semantic memory-recall CLI** over a personal markdown corpus. Ask a
question in natural language; get back ranked `path:line` snippets from across the whole
corpus, by meaning. Fully local (offline embeddings via llama.cpp's `llama serve`), no framework, a few
hundred lines of Python, one SQLite file.

```
$ recall "why did we drop the legacy queue worker"
[V+K] memory/decisions/queue_migration_decision.md:1
    Decision: retire the legacy queue worker in favor of the managed broker ...
```

## Reading results

Each hit is tagged with **V** = vector (semantic match), **K** = keyword (literal FTS match):

| tag | meaning | what to trust |
|---|---|---|
| `[V+K]` | matched by **both** | highest confidence — the file means it *and* says it |
| `[V]` | semantic only, no keyword overlap | the save grep can't make — trust it even though the words don't line up |
| `[K]` | keyword only | literal match; in default mode, seeing `[K]` means the embedder was down and recall fell back to keyword-only |

In default (vector) mode every hit is at least `[V]`; `[K]`-only results appear only when
the embedding server is unreachable (automatic fallback) or in `--hybrid` mode.

## Usage

The installed entry point is `~/.recall/recall.py` (a thin launcher; see
[Runtime layout](#runtime-layout)). Full command set:

```sh
python3 ~/.recall/recall.py "natural-language query"   # ranked path:line + snippet
python3 ~/.recall/recall.py "..." --hybrid             # RRF hybrid (vector+keyword)
python3 ~/.recall/recall.py "..." --vector             # force vector even if config default is hybrid
python3 ~/.recall/recall.py "..." -k 8                 # more hits (default 5)
python3 ~/.recall/recall.py index                      # incremental reindex (only changed files re-embed)
python3 ~/.recall/recall.py index --rebuild            # wipe + full reindex (after changing embed model)
python3 ~/.recall/recall.py index --publish            # reindex, then publish a snapshot (writer only)
python3 ~/.recall/recall.py publish                    # publish a fresh snapshot from the current db (writer only)
python3 ~/.recall/recall.py add "durable fact" --title "short title"   # write a dated intake note
python3 ~/.recall/recall.py add "durable fact" --publish               # index + publish it (writer only)
python3 ~/.recall/recall.py stats                      # role/config/counts, or missing-reader-snapshot diagnosis
```

`--vector` and `--hybrid` are mutually exclusive. The `recall` shorthand is an interactive
shell alias only — non-interactive callers (agents) must use the full `python3 .../recall.py` path.

Requires: `llama serve` running with `ggml-org/embeddinggemma-300M-GGUF:Q8_0` downloaded
(preset must set `embeddings = true`, `ub = 2048` for that model), and `python3 -m pip install libsql`.

### Reader, writer, and standalone roles

One SQLite index can be shared across machines through a file-sync folder (Syncthing,
Dropbox, etc.). Each machine plays one role, set by config:

| role | config | indexes / publishes | `recall "query"` | `add` |
|---|---|---|---|---|
| **standalone** | default (no `read_only`, no `publish_path`) | yes, writes its own local db | yes | writes an intake note **and** reindexes locally |
| **writer** | `publish_path` set | yes; `index --publish` / `publish` write a WAL-free snapshot into the sync folder | yes | intake note + local reindex; publish to share it |
| **reader** | `read_only: true` | never — `index`, `--rebuild`, `publish` are refused | yes, against the synced snapshot (opened read-only) | writes the dated intake note only; **does not touch the reader database** (the writer picks the note up on its next index and the synced snapshot carries it back) |

Exactly one machine in a shared set is the writer. Readers never `ALTER TABLE` or write the
db, so they tolerate a snapshot published by an older or newer engine.

### Source of truth and catalog files

```text
Individual Markdown notes are source records. memory.db is derived. MEMORY.md is
excluded by default because catalogs commonly duplicate source notes. A project that
has not migrated unique catalog-only content may temporarily set "exclude_files": []
in its private config; migrate that content before restoring the default.
```

### Runtime layout

`setup/install.sh` seeds `~/.recall/recall.py` **once** — and what it seeds is
`tools/recall/launcher.py`, a stable launcher with no retrieval logic. The launcher locates
the canonical engine at `tools/recall/recall.py` in the agent-rules checkout, re-execs under
`~/.recall/.venv` when that venv exists, and hands off. So:

- **fresh installs** get the launcher; engine fixes in the repo take effect immediately, no re-copy
- **an existing `~/.recall/recall.py` is never overwritten** (`copy_once` refuses a populated target)
- migrating a pre-launcher `~/.recall/recall.py` to the launcher is a deliberate gated step:
  back up the current file, run the public engine's own tests, confirm retrieval parity against
  the corpus's private benchmark, and get explicit owner approval before replacing it
- set `AGENT_RULES_HOME` if the checkout is not at `~/.agent-rules`

`~/.recall/` holds only device-local state after that: `config.json`, `.venv`, `memory.db`,
and `bench_labels.json`. None of it is tracked or synced through Git.

## How it works

Five small parts, no LangChain / Pinecone / cloud:

| part | what it does |
|---|---|
| `embed()` | POST to local **llama-server** `/v1/embeddings` (`embeddinggemma`, 768-dim) → query/doc vector |
| `chunk_md()` | split markdown into ~1100-char chunks on blank-line boundaries, track line numbers |
| `connect()` | **SQLite/libSQL**: a `chunks` table with an `F32_BLOB(768)` vector column + an **FTS5** virtual table |
| `cmd_index()` | walk Markdown source files (excluding legacy `MEMORY.md` catalogs), sha1-hash each, **re-embed only changed files** (incremental) |
| `cmd_recall()` | retrieval (below) |

Retrieval is two SQL queries: a brute-force cosine scan
(`vector_distance_cos(emb, vector32(?))`) for the vector arm, and an FTS5 `MATCH` for the
keyword arm. **Default ranking is vector-only** — it wins on this corpus (see Benchmarks);
keyword fusion drags near-miss files up and pollutes the rank. The keyword arm still earns its
keep as the **automatic fallback** when the embedder is unreachable, and as the opt-in
`--hybrid` mode (Reciprocal Rank Fusion, `score += 1/(60+rank)`) for noisier or larger corpora.

## Configuration

Corpus paths are **not** hardcoded. First run looks, in order, for:

1. `~/.recall/config.json` (copy `config.example.json` and edit the paths)
2. a `RECALL_SOURCES` env var (same JSON shape)
3. a generic placeholder default (prints a hint to create `config.json`)

The embedder endpoint/model are also overridable per machine:
`RECALL_EMBED_URL` (default `http://localhost:8080/v1/embeddings`) and
`RECALL_EMBED_MODEL` (default `ggml-org/embeddinggemma-300M-GGUF:Q8_0`).


```jsonc
// ~/.recall/config.json
{ "sources": [
    { "label": "memory", "path": "~/notes/memory" },
    { "label": "vault",  "path": "~/notes/vault" }
  ],
  "retrieval_mode": "vector",   // "vector" (default) or "hybrid"
  "read_only": false,           // true → reader: never indexes or publishes
  "publish_path": null          // set on the writer → snapshot target in the sync folder
}
```

`retrieval_mode` sets the default ranker. Keep it `vector` unless this corpus's **own**
private benchmark (`bench_quality.py` against the real `bench_labels.json`) shows `hybrid`
winning on hit@k / MRR. A per-query `--vector` / `--hybrid` flag overrides it either way.

If `inbox` is configured, it must be directly walkable inside an available `source`: not
outside it, below an excluded directory, or through a child-directory symlink. This prevents
`add --publish` from shipping a snapshot that omits the newly written note. If indexing is
deferred because the embedder is unavailable, the note remains saved but publication is
skipped; retry with `index --publish` once the embedder is reachable.

`config.json` and `bench_labels.json` are gitignored (they describe a personal corpus); only
the `.example` templates are tracked. Individual Markdown notes are the source of truth;
`MEMORY.md` catalog files are skipped because they duplicate those notes and pollute retrieval.

## Agent integration

`recall` is a plain CLI — any agent that can run a shell command can use it, no MCP server.
Add one instruction to your agent's instructions file, using the **absolute** command (the
`recall` alias does NOT exist in a non-interactive shell):

```markdown
## Memory Recall
Before grepping or reading files where you don't already know which file holds the answer,
first run:

    python3 ~/.recall/recall.py "natural-language query"

It returns ranked path:line snippets across the whole corpus. Open full files only when a
snippet is insufficient. Requires the embedding server; if it errors, fall back to grep.
```

Which file: `AGENTS.md` is the cross-tool standard (Codex, OpenCode); `CLAUDE.md` / `GEMINI.md`
are tool-specific. Keep `AGENTS.md` canonical and symlink the rest to it
(`ln -s AGENTS.md CLAUDE.md`) so one edit reaches every runtime.

**Keeping the index fresh.** The index is a derived cache; it goes stale when memory files
change. Reindex on a trigger or a schedule:

- *Claude Code hook* — a `PostToolUse` hook on `Write|Edit` that runs `recall.py index`
  (incremental) when the edited path is under a `memory/` dir. (How the author's machine is wired.)
- *cron / periodic* — `recall.py index` is incremental, so a cheap periodic run is fine.

(Prefer a typed tool call? Wrap `recall.py` in a thin MCP server.)

## Benchmarks

From a 173-chunk cross-agent memory corpus; run `python3 bench_*.py` from this dir.

**Quality** (30 labeled queries, half adversarial paraphrases with low keyword overlap):

| mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| **vector** | 29/30 | 30/30 | 30/30 | 0.978 |
| hybrid | 27/30 | 29/30 | 30/30 | 0.942 |
| fts | 22/30 | 27/30 | 27/30 | 0.825 |

Vector wins on this short, semantically-distinct corpus — hence the default. An earlier
1,901-chunk notes-vault run flipped it (hybrid was the only mode to land every query top-3),
which is why `--hybrid` stays opt-in. **Measure per corpus and default to what wins.**

Two findings: adjacent memories on one topic can collide in retrieval — sharpening each file's
`description:` to be distinctive moved the colliders from rank 7–9 back to #1 without touching
the ranker; and the labeled set must grow with the corpus or it stops testing anything new.

**vs. grep** (`bench_vs_grep.py`): recall hit@3 29/30; grep cleanly wins only 10/30 (tiny
haystacks); recall found 14/30 queries grep missed entirely, none the reverse. Recall's edge
is the don't-know-the-file, whole-corpus lookup.

**Efficiency** (`bench_efficiency.py`): ~449 tokens/query — break-even with reading the single
correct file, ~106× smaller than the whole corpus; ~87 ms end-to-end (p50, mostly the embedder
hop); 1.1 MB for 173 chunks.

## Design decisions

- **Brute-force cosine, no ANN index.** At <10k chunks an exact scan is sub-ms and keeps the
  DB ~1 MB; the libSQL DiskANN index bloated it to 155 MB for no gain. Add ANN only past ~10×
  this scale.
- **Vector default, hybrid opt-in** — chosen by measurement, not dogma (see Benchmarks).
- **Embedder benchmarked, not assumed.** `embeddinggemma` (768-d) beat `qwen3-embedding:0.6b`
  here despite the latter's higher MTEB score, and needs a ≥~1k-token context window for the
  ~2,200-char chunks (`nomic-embed-text-v2-moe` overflows ~32% of them).
- **CLI, not MCP.** One executable every agent runtime can shell out to.
- **Index excluded from version control / sync** — it's a derived binary cache; see `.gitignore`.

## Limitations

- Retrieval quality depends on chunking + embedder; chunking here is deliberately naive.
- Embedder down → recall degrades to keyword-only (FTS) with a stderr warning, results tagged
  `[K]`; indexing still requires the embedder (it must embed).
- Shared snapshots use one designated writer; readers intentionally cannot index or publish.
