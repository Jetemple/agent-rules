# recall

A tool-agnostic **semantic memory-recall CLI** over a personal markdown corpus. Ask a
question in natural language; get back ranked `path:line` snippets from across the whole
corpus, by meaning (with a keyword arm available for fallback and fusion). Fully local
(offline embeddings), zero framework, ~400 lines of Python, one SQLite file.

```
$ recall "why did we drop the legacy queue worker"
[V+K] ~/notes/decisions/queue_migration_decision.md:1
    Decision: retire the legacy queue worker in favor of the managed broker ...
```
`[V+K]` = matched by both vector and keyword · `[V]` = semantic only · `[K]` = keyword only.

## How it works

Five parts, no LangChain / Pinecone / cloud:

| part | what it does |
|---|---|
| `embed()` | POST to local **Ollama** (`embeddinggemma`, 768-dim) → query/doc vector |
| `chunk_md()` | split markdown into ~1100-char chunks on blank-line boundaries, track line numbers |
| `connect()` | **SQLite/libSQL**: a `chunks` table with an `F32_BLOB(768)` vector column + an **FTS5** virtual table |
| `cmd_index()` | walk files, sha1-hash each, **re-embed only changed files** (incremental) |
| `cmd_recall()` | the retrieval ↓ |

Retrieval is two SQL queries:

```sql
-- dense (default ranking): exact brute-force cosine scan (libSQL native vector fn)
SELECT id FROM chunks ORDER BY vector_distance_cos(emb, vector32(?)) LIMIT 20;
-- sparse: keyword
SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 20;
```

**The default ranking is vector-only.** On this short, semantically-distinct memory corpus
that measures best (see Benchmarks) — keyword fusion drags near-miss files up and pollutes
the rank. The keyword arm still earns its keep two ways: it's the **automatic fallback** when
the embedder is unreachable (results tagged `[K]`), and it powers an opt-in **hybrid** mode
(`--hybrid`) that merges both arms with **Reciprocal Rank Fusion** (`score += 1/(60+rank)`)
for noisier or larger corpora where neither arm alone is robust.

## Benchmarks

Numbers below are from a 173-chunk **cross-agent memory corpus** (every Claude project's
`memory/` dir + `~/.codex/memories`). Run `python3 bench_*.py` from this dir. An earlier
run on a larger 1,901-chunk notes vault is summarized after, because the two corpora
tell genuinely different stories.

**Retrieval quality** — 30 labeled queries (`bench_quality.py`). Half are friendly phrasings
that share keywords with the answer; half are adversarial paraphrases with deliberately low
keyword overlap (the realistic ad-hoc case):

| mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| **vector** | **29/30** | 30/30 | 30/30 | **0.978** |
| hybrid | 27/30 | 29/30 | 30/30 | 0.942 |
| fts | 22/30 | 27/30 | 27/30 | 0.825 |

Vector-only wins on every metric — so it's the **default**. The reason is corpus shape:
short, semantically-distinct memory files are exactly where embeddings shine, and keyword
fusion only drags near-miss files up and pollutes the fused rank. On the adversarial subset
alone the gap is wider (vector 12/14 hit@1 vs hybrid 10/14), which is *why* the default
matters — friendly queries hide the difference, hard ones expose it. The lesson isn't "drop
hybrid"; it's "**measure per corpus and default to what wins**." On the noisier vault below,
hybrid was the only robust mode — so `--hybrid` is kept as an opt-in.

Two findings worth noting from the adversarial set: (1) when one topic is split into two
adjacent memories, retrieval can confuse the siblings — the fix was **sharpening each file's
`description:` to be distinctive**, which moved both colliding files from rank 7–9 back to
rank 1 without touching the ranker; (2) the labeled set must grow with the corpus or it
stops testing anything new.

*Earlier 1,901-chunk notes-vault run (14 queries):* hybrid was the only mode to land top-3 on
every query (hit@3 14/14, MRR 0.893); vector's worst case was rank 19, keyword's rank 5,
hybrid never exceeded rank 2. **This is the corpus where `--hybrid` pays off.**

**vs. grep** — the tool you'd otherwise use without the index (`bench_vs_grep.py`):

```
recall hit@3:                       29/30
smart-grep clean win (≤3 files):    10/30   ← tiny haystack; grep alone suffices
grep MISSED entirely, recall got it: 14/30   ← semantic saves grep can't make
grep got it, recall missed:          0/30
median naive grep haystack:          47 files
```
Honest caveat: when you already **know the file** and the term is literal, `grep` wins and
recall is overkill (here, a third of the queries). Recall's edge is the *don't-know-the-file,
whole-corpus* lookup — and the 14/30 semantic-only saves grep can't make.

**Efficiency** (`bench_efficiency.py`): ~449 tokens/query — about break-even with reading the
single correct file (~0.9×), but **106× smaller** than dumping the whole corpus. The token
win is "rank the right file #1 so you don't read a 47-file haystack," not a smaller snippet.
~87 ms end-to-end (p50; ~85 ms is the Ollama embed hop, ~2 ms the DB scan) · 1.1 MB for 173
chunks.

## Configuration

The corpus paths are **not** hardcoded. On first run `recall` looks, in order, for:

1. `~/.recall/config.json` (copy `config.example.json` and edit the paths)
2. a `RECALL_SOURCES` env var (same JSON shape)
3. a generic placeholder default (prints a hint to create `config.json`)

```jsonc
// ~/.recall/config.json
{ "sources": [
    { "label": "memory", "path": "~/notes/memory" },
    { "label": "vault",  "path": "~/notes/vault" }
] }
```

Benchmark labels work the same way: `bench_quality.py` loads `~/.recall/bench_labels.json`
if present, else the tracked `bench_labels.example.json`. Both `config.json` and
`bench_labels.json` are gitignored (they describe a personal corpus); only the
`.example` templates are tracked.

## Usage

```
recall "your question"        # vector recall → path:line + snippet
recall "..." --hybrid         # RRF hybrid (vector+keyword) — for noisier/larger corpora
recall "..." -k 8             # more hits (default 5)
recall index                  # incremental reindex (only changed files re-embed)
recall index --rebuild        # wipe + full reindex (after changing embed model)
recall stats                  # file/chunk counts + db size
```
Requires: Ollama running with `embeddinggemma` pulled, and `python3 -m pip install libsql`.
The `recall` shorthand is a shell alias (`alias recall='python3 ~/.recall/recall.py'`);
**automated callers must use the full `python3 .../recall.py` path** (the alias only exists
in interactive shells).

## Agent integration (route it to every runtime)

`recall` is a plain CLI, so any agent that can run a shell command can use it — no MCP
server, no plugin. You wire it by adding one instruction to whatever **instructions file**
your agent reads, pointing at the **absolute** command. (The `recall` alias does NOT exist
in an agent's non-interactive shell — always use the full `python3 .../recall.py` path, or
agents get `command not found`.)

| runtime | instructions file it reads |
|---|---|
| Claude Code | `CLAUDE.md` (project) or `~/.claude/CLAUDE.md` (global) |
| Codex | `AGENTS.md` |
| OpenCode | `AGENTS.md` |
| Gemini CLI | `GEMINI.md` |

`AGENTS.md` is the emerging cross-tool standard; `CLAUDE.md` / `GEMINI.md` are tool-specific.
Keep `AGENTS.md` as the canonical file and symlink the rest to it (`ln -s AGENTS.md CLAUDE.md`)
so a single edit reaches every runtime at once.

Drop this block into that file:

```markdown
## Memory Recall
Before grepping or reading files to answer a question where you do not already know
which file holds the answer, first run:

    python3 ~/.recall/recall.py "natural-language query"

It returns ranked path:line snippets across the whole corpus. Open full files only
when a snippet is insufficient. Requires Ollama; if it errors, fall back to grep.
```

Instructions are advisory, not enforced — scope the rule to "I don't know which file"
lookups so agents don't invoke it when a plain `grep` or an already-known fact would do.

**Keeping the index fresh.** The index is a derived cache; it goes stale when memory files
change. Either reindex on a trigger or on a schedule:

- *Claude Code hook* — a `PostToolUse` hook on `Write|Edit` that runs `recall.py index`
  (incremental, async) when the edited path is under a `memory/` dir. One edit → fresh index,
  no manual step. (This is how the author's machine is wired.)
- *cron / periodic* — `recall.py index` is incremental (only changed files re-embed), so a
  cheap periodic run is fine if your runtime has no hook mechanism.
(Prefer a typed tool call over a shell-out? Wrap `recall.py` in a thin MCP server instead.)

## Design decisions

- **Brute-force cosine, no ANN index.** At <10k chunks an exact scan is sub-ms and keeps the
  DB ~1 MB; the libSQL DiskANN index bloated it to 155 MB for no quality gain. Add ANN only
  past ~10× this scale, where the embed hop stops being the bottleneck.
- **Vector default, hybrid opt-in — chosen by measurement, not dogma.** The ablation above
  shows vector-only wins on *this* short/distinct memory corpus, while the larger noisier vault
  needed hybrid. So the default is vector and `--hybrid` restores RRF fusion; the "right" mode
  is a per-corpus call you make with `bench_quality.py`, not a fixed belief.
- **Embedder choice is benchmarked, not assumed.** `embeddinggemma` (768-d) beat or tied
  `qwen3-embedding:0.6b` on this corpus despite the latter's higher MTEB retrieval score —
  identical on hybrid, *better* on vector-only (hit@1 11 vs 8). Leaderboard scores don't
  transfer; measure on your own data. The embedder also needs a ≥~1k-token context window for
  the ~2,200-char chunks: `nomic-embed-text-v2-moe` (512 ctx) overflows ~32% of them.
- **CLI, not MCP.** One executable every agent runtime can shell out to.
- **Index excluded from version control / sync.** It's a derived binary cache rebuilt from the
  source markdown; see `.gitignore`.

## Limitations

- Retrieval quality depends on chunking + embedding-model choice; chunking here is deliberately
  naive (fixed-size on blank lines).
- If Ollama is down, recall degrades to **keyword-only (FTS)** with a stderr warning rather
  than crashing; results are tagged `[K]`. Indexing still requires Ollama (it must embed).
- Single-corpus, single-machine. The DB is a per-machine cache.
