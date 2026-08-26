# recall

A tool-agnostic **semantic memory-recall CLI** over a personal markdown corpus. Ask a
question in natural language; get back ranked `path:line` snippets from across the whole
corpus, by meaning. Fully local (offline embeddings via llama.cpp's `llama serve`), no framework, ~300 lines
of Python, one SQLite file.

```
$ recall "why did we drop the legacy queue worker"
[V+K] ~/notes/decisions/queue_migration_decision.md:1
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

```
recall "your question"        # vector recall → path:line + snippet
recall "..." --hybrid         # RRF hybrid (vector+keyword) — for noisier/larger corpora
recall "..." -k 8             # more hits (default 5)
recall index                  # incremental reindex (only changed files re-embed)
recall index --rebuild        # wipe + full reindex (after changing embed model)
recall stats                  # file/chunk counts + db size
```

Requires: `llama serve` running with `ggml-org/embeddinggemma-300M-GGUF:Q8_0` downloaded
(preset must set `embeddings = true`, `ub = 2048` for that model), and `python3 -m pip install libsql`.
The `recall` shorthand is a shell alias — non-interactive callers (agents) must use the full
`python3 .../recall.py` path.

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
] }
```

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
- Single-corpus, single-machine. The DB is a per-machine cache.
