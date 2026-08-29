#!/usr/bin/env python3
"""
recall — tool-agnostic semantic memory recall over a notes corpus + agent memory.

Engine : libSQL (native F32_BLOB vectors + brute-force vector_distance_cos) + FTS5.
Embed  : llama.cpp `llama serve` `embeddinggemma` (768-d, fully offline).
Recall : vector-only by default (see cmd_recall); --hybrid adds FTS5 + Reciprocal Rank
         Fusion, and FTS-only is the automatic fallback when the embedder is unreachable.
Output : each hit is tagged by which arm matched — [V+K] both, [V] semantic only (the
         grep-can't-find-it case), [K] keyword only (or the embedder-down fallback).

Usage:
  recall.py index            # incremental (only changed files) — run this before first query
  recall.py index --rebuild  # wipe + full reindex
  recall.py "query text"     # vector recall, prints file:line + snippet
  recall.py "query" --hybrid # RRF hybrid for noisier/larger corpora
  recall.py stats
Both Codex and Claude just shell out:  recall.py "how do I rebuild the index"
"""
import os, sys, json, hashlib, urllib.request, urllib.error, argparse, textwrap

# ---- config -----------------------------------------------------------------
# The engine stays importable with no third-party deps (unit tests exercise
# config/corpus/formatting logic directly). `libsql` is imported lazily inside
# connect(); virtualenv selection is the launcher's job, not the engine's.
HOME      = os.path.expanduser("~")
DIM       = 768
CHUNK_MAX = 1100          # chars per chunk (soft)
RRF_K     = 60            # reciprocal-rank-fusion constant

# Corpus + DB config is loaded at runtime, never hardcoded, so this file can be
# shared/published without leaking personal paths. Priority order:
#   1. ~/.recall/config.json  (gitignored; the owner's real paths)
#   2. env vars  (RECALL_SOURCES / RECALL_DB / RECALL_PUBLISH / RECALL_READONLY /
#                 RECALL_RETRIEVAL_MODE / RECALL_EMBED_URL / RECALL_EMBED_MODEL)
#   3. a generic built-in default (+ a one-line hint to create config.json)
# Copy config.example.json -> config.json and edit it to point at your corpus.
#
# config.json keys:
#   sources         [{label, path}]  corpus roots to index (markdown)
#   db_path         str   where THIS machine's DB lives (default ~/.recall/memory.db)
#   publish_path    str   writer-only: where `publish` writes the synced snapshot
#   read_only       bool  reader: open the DB read-only; refuse index/add/publish
#   inbox           str   where `add` writes new notes (default <first source>/_inbox)
#   retrieval_mode  str   "vector" (default, portable) or "hybrid" (RRF fusion)
#   exclude_files   [str] basenames never indexed (default ["MEMORY.md"])
#   embed_url       str   embeddings endpoint (OpenAI-compatible)
#   embed_model     str   embeddings model id
CONFIG_PATH = os.path.join(HOME, ".recall", "config.json")
DEFAULT_SOURCES = [
    ("memory", os.path.join(HOME, "notes", "memory")),
    ("vault",  os.path.join(HOME, "notes", "vault")),
]

def _expand(path):
    return os.path.expanduser(path) if path else path

def _boolean(value, field):
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{field} must be a boolean value")

def _string_list(value, default):
    if value is None:
        return list(default)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError("exclude_files must be a list of non-empty strings")
    return value

def _parse_sources(obj):
    """Turn a {"sources":[{"label","path"}]} JSON object into [(label, path)]."""
    out = []
    for s in obj.get("sources", []):
        label = s.get("label")
        path = s.get("path")
        if label and path:
            out.append((label, os.path.expanduser(path)))
    return out

def load_config():
    raw = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            raw = json.load(handle)

    sources = _parse_sources(raw)
    if not sources:
        env_sources = os.environ.get("RECALL_SOURCES")
        sources = _parse_sources(json.loads(env_sources)) if env_sources else []
    if not sources:
        sources = [(label, _expand(path)) for label, path in DEFAULT_SOURCES]

    retrieval_mode = os.environ.get(
        "RECALL_RETRIEVAL_MODE", raw.get("retrieval_mode", "vector")
    ).strip().lower()
    if retrieval_mode not in {"vector", "hybrid"}:
        raise ValueError("retrieval_mode must be 'vector' or 'hybrid'")

    return {
        "sources": sources,
        "db_path": _expand(os.environ.get("RECALL_DB") or raw.get("db_path")
                           or os.path.join(HOME, ".recall", "memory.db")),
        "publish_path": _expand(os.environ.get("RECALL_PUBLISH") or raw.get("publish_path")),
        "read_only": _boolean(
            os.environ.get("RECALL_READONLY", raw.get("read_only", False)), "read_only"
        ),
        "inbox": _expand(raw.get("inbox")) or os.path.join(sources[0][1], "_inbox"),
        "retrieval_mode": retrieval_mode,
        "exclude_files": set(_string_list(raw.get("exclude_files"), ["MEMORY.md"])),
        "embed_url": os.environ.get("RECALL_EMBED_URL", raw.get("embed_url", "http://localhost:8080/v1/embeddings")),
        "embed_model": os.environ.get("RECALL_EMBED_MODEL", raw.get("embed_model", "ggml-org/embeddinggemma-300M-GGUF:Q8_0")),
    }

try:
    CFG = load_config()
except (json.JSONDecodeError, OSError, ValueError) as error:
    if __name__ == "__main__":
        print(f"recall: invalid configuration: {error}", file=sys.stderr)
        raise SystemExit(2)
    raise

SOURCES       = CFG["sources"]
DB_PATH       = CFG["db_path"]
PUBLISH_PATH  = CFG["publish_path"]
READ_ONLY     = CFG["read_only"]
RETRIEVAL_MODE = CFG["retrieval_mode"]
EXCLUDE_FILES = CFG["exclude_files"]
EMBED_URL     = CFG["embed_url"]
MODEL         = CFG["embed_model"]
# Hard constitution rules: never index these. `_recall` holds the published DB
# snapshot (inside the synced folder); excluding it keeps the walk from touching it.
EXCLUDE_DIRS = {"_scratch", "_archive", ".git", "node_modules", ".obsidian", "_recall"}

# ---- embedding --------------------------------------------------------------
def embed(text, is_query, _tries=5):
    # EmbeddingGemma documented retrieval prompts
    prompt = (f"task: search result | query: {text}" if is_query
              else f"title: none | text: {text}")
    body = json.dumps({"model": MODEL, "input": prompt}).encode()
    for attempt in range(_tries):
        try:
            req = urllib.request.Request(EMBED_URL, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["data"][0]["embedding"]
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500:
                # permanent client error (bad model name / bad request): no retry
                raise urllib.error.URLError(
                    f"embedder rejected request ({e.code}): {e.read(200)!r}") from e
            if attempt == _tries - 1:
                raise
            import time
            time.sleep(2 * (attempt + 1))   # backoff; rides out a server hiccup

# ---- markdown chunking (tracks start line for citations) --------------------
def chunk_md(text):
    lines = text.split("\n")
    chunks, buf, start = [], [], 1
    size = 0
    for i, ln in enumerate(lines, 1):
        if not buf:
            start = i
        buf.append(ln)
        size += len(ln) + 1
        # break on blank-line boundary once over target, or hard cap
        if (size >= CHUNK_MAX and ln.strip() == "") or size >= CHUNK_MAX * 2:
            body = "\n".join(buf).strip()
            if body:
                chunks.append((start, body))
            buf, size = [], 0
    body = "\n".join(buf).strip()
    if body:
        chunks.append((start, body))
    return chunks

# ---- db ---------------------------------------------------------------------
def connect(read_only=None):
    """Open the DB. Readers open the synced snapshot read-only and never create
    or alter schema; writers create the schema if missing and migrate the `rel`
    column idempotently by inspecting the table first (so a genuine database
    error still propagates instead of being swallowed by a blanket except)."""
    import libsql
    reader = READ_ONLY if read_only is None else read_only
    if reader:
        connection = libsql.connect(f"file:{DB_PATH}?mode=ro", _uri=True)
        return connection, connection.cursor()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    connection = libsql.connect(DB_PATH)
    cursor = connection.cursor()
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS chunks(
        id INTEGER PRIMARY KEY, source TEXT, path TEXT, rel TEXT, line INTEGER,
        txt TEXT, emb F32_BLOB({DIM}))""")
    # `rel` (path relative to its source root) makes citations machine-portable;
    # older DBs predate it. Inspect the schema, then add the column only if it is
    # genuinely absent.
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(chunks)").fetchall()}
    if "rel" not in columns:
        cursor.execute("ALTER TABLE chunks ADD COLUMN rel TEXT")
    # No ANN index: corpus is small (<10k chunks), so a brute-force
    # vector_distance_cos scan is exact, sub-ms, and keeps the DB ~5MB
    # instead of ~155MB (DiskANN stores ~50 raw neighbor vectors/node).
    cursor.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS fts
        USING fts5(txt, content='chunks', content_rowid='id')""")
    cursor.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, hash TEXT)")
    connection.commit()
    return connection, cursor


def _chunks_has_rel(cursor):
    return "rel" in {row[1] for row in cursor.execute("PRAGMA table_info(chunks)").fetchall()}


def _chunk_select_columns(cursor):
    return "source,path,rel,line,txt" if _chunks_has_rel(cursor) else "source,path,NULL AS rel,line,txt"

def iter_files():
    for source, root in SOURCES:
        if not os.path.isdir(root):
            continue
        for directory, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in EXCLUDE_DIRS]
            for name in sorted(files):
                if name.endswith(".md") and name not in EXCLUDE_FILES:
                    yield source, root, os.path.join(directory, name)

# ---- commands ---------------------------------------------------------------
def _refuse_if_readonly(action):
    if READ_ONLY:
        print(f"recall: this machine is read_only; refusing to {action}. "
              f"(Only the writer indexes/writes the shared DB.)", file=sys.stderr)
        raise SystemExit(2)


def _validate_source_roots():
    """A missing configured root (e.g. an unmounted synced volume) must abort
    before any stale-file deletion, not be silently treated as an empty corpus."""
    missing = [(label, root) for label, root in SOURCES if not os.path.isdir(root)]
    if missing:
        for label, root in missing:
            print(f"recall: source root missing for {label}: {root}", file=sys.stderr)
        raise SystemExit(2)


def _sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def _yaml_scalar(value):
    """JSON strings are valid YAML scalars, so this safely quotes frontmatter
    values that contain colons, quotes, or leading punctuation."""
    return json.dumps(str(value), ensure_ascii=False)


def _citation(source, path, rel):
    """Machine-portable citation: source-relative when the row has `rel`, else a
    home-relative fallback for pre-migration rows."""
    return f"{source}/{rel}" if rel else os.path.relpath(path, HOME)


def _index_one_file(cur, source, root, path, raw, h):
    """(Re)embed a single changed file. Returns the number of chunks embedded."""
    rel = os.path.relpath(path, root)
    cur.execute("SELECT id FROM chunks WHERE path=?", (path,))
    for (cid,) in cur.fetchall():
        cur.execute("DELETE FROM fts WHERE rowid=?", (cid,))
    cur.execute("DELETE FROM chunks WHERE path=?", (path,))
    n_chunks = 0
    for start, body in chunk_md(raw):
        v = embed(body, is_query=False)
        cur.execute(
            "INSERT INTO chunks(source,path,rel,line,txt,emb) VALUES (?,?,?,?,?,vector32(?))",
            (source, path, rel, start, body, str(v)))
        cid = cur.lastrowid
        cur.execute("INSERT INTO fts(rowid,txt) VALUES (?,?)", (cid, body))
        n_chunks += 1
    cur.execute("INSERT OR REPLACE INTO files(path,hash) VALUES (?,?)", (path, h))
    return n_chunks


def _index_all_files(con, cur, commit_each):
    """Walk the corpus, (re)index changed files, prune vanished ones.
    Returns the count of changed files. When commit_each is true an incremental
    run may commit after each changed file; a rebuild passes false so the caller
    owns one atomic transaction."""
    seen, changed, n_chunks = set(), 0, 0
    for source, root, path in iter_files():
        seen.add(path)
        with open(path, encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
        h = hashlib.sha1(raw.encode()).hexdigest()
        cur.execute("SELECT hash FROM files WHERE path=?", (path,))
        row = cur.fetchall()
        if row and row[0][0] == h:
            continue                       # unchanged -> skip (incremental)
        changed += 1
        n_chunks += _index_one_file(cur, source, root, path, raw, h)
        if commit_each:
            con.commit()
        print(f"  indexed {os.path.relpath(path, HOME)}", file=sys.stderr)
    # drop files that disappeared
    cur.execute("SELECT path FROM files")
    for (p,) in cur.fetchall():
        if p not in seen:
            cur.execute("SELECT id FROM chunks WHERE path=?", (p,))
            for (cid,) in cur.fetchall():
                cur.execute("DELETE FROM fts WHERE rowid=?", (cid,))
            cur.execute("DELETE FROM chunks WHERE path=?", (p,))
            cur.execute("DELETE FROM files WHERE path=?", (p,))
    print(f"done. {changed} files changed, {n_chunks} chunks (re)embedded.", file=sys.stderr)
    return changed


def cmd_index(rebuild=False):
    _refuse_if_readonly("index")
    _validate_source_roots()
    con, cur = connect()
    if rebuild:
        # One explicit transaction: an embedding, filesystem, or database
        # interruption during a rebuild restores the previous index rather than
        # leaving it half-wiped.
        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute("INSERT INTO fts(fts) VALUES (?)", ("delete-all",))
            cur.execute("DELETE FROM chunks")
            cur.execute("DELETE FROM files")
            changed = _index_all_files(con, cur, commit_each=False)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        return changed
    changed = _index_all_files(con, cur, commit_each=True)
    con.commit()
    return changed


def cmd_publish():
    """Publish a clean, WAL-free snapshot of the DB for Syncthing to replicate.
    VACUUM INTO writes a fresh single file; os.replace makes it appear atomically
    so readers (and Syncthing) never observe a half-written database. A failed
    VACUUM INTO leaves the current published snapshot untouched."""
    _refuse_if_readonly("publish")
    if not PUBLISH_PATH:
        print("recall: no publish_path configured. Set it in config.json on the "
              "writer to enable shared-snapshot publishing.", file=sys.stderr)
        raise SystemExit(2)
    os.makedirs(os.path.dirname(PUBLISH_PATH), exist_ok=True)
    temporary = PUBLISH_PATH + ".tmp"
    if os.path.exists(temporary):
        os.remove(temporary)               # VACUUM INTO requires a non-existent target
    connection, cursor = connect()
    cursor.execute(f"VACUUM INTO {_sql_literal(temporary)}")
    connection.commit()
    connection.close()
    os.replace(temporary, PUBLISH_PATH)     # atomic publish
    print(f"published snapshot -> {PUBLISH_PATH} "
          f"({os.path.getsize(PUBLISH_PATH)//1024} KB)", file=sys.stderr)

def fts_query(q):
    # safe FTS5: quote each alnum token, OR them
    toks = ["".join(c for c in t if c.isalnum()) for t in q.split()]
    toks = [t for t in toks if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in toks) or '""'

def cmd_recall(q, k=5, pool=20, hybrid=False):
    con, cur = connect()
    # Default ranking is VECTOR-ONLY. On this short, semantically-distinct memory
    # corpus, two benchmarks (bench_quality.py and the adversarial new-memory set)
    # show pure vector beats RRF hybrid — keyword fusion drags near-miss files up
    # and pollutes the fused rank (e.g. near-duplicate topical memories). Pass
    # hybrid=True (--hybrid) to restore RRF for noisier/larger corpora.
    # If the embedder is down/unreachable, degrade to FTS-only instead of crashing.
    vec_ids = []
    try:
        qv = str(embed(q, is_query=True))
        # vector ranking: exact brute-force cosine scan (Turso native fn)
        cur.execute("""SELECT id FROM chunks
                       ORDER BY vector_distance_cos(emb, vector32(?)) LIMIT ?""", (qv, pool))
        vec_ids = [r[0] for r in cur.fetchall()]
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        print(f"recall: embedder unavailable ({e}); falling back to keyword-only.",
              file=sys.stderr)
    # keyword ranking (always computed: used for V+K tagging, hybrid fusion, and
    # as the sole signal when the embedder is unavailable)
    cur.execute(f"""SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?""",
                (fts_query(q), pool))
    fts_ids = [r[0] for r in cur.fetchall()]
    if hybrid or not vec_ids:
        # reciprocal rank fusion (or FTS-only when the embedder is down)
        scores = {}
        for rank, cid in enumerate(vec_ids):
            scores[cid] = scores.get(cid, 0) + 1.0 / (RRF_K + rank)
        for rank, cid in enumerate(fts_ids):
            scores[cid] = scores.get(cid, 0) + 1.0 / (RRF_K + rank)
        top = sorted(scores, key=scores.get, reverse=True)[:k]
    else:
        # vector-primary: rank by cosine, keep vector order intact
        top = vec_ids[:k]
    if not top:
        print("(no matches)")
        return
    for cid in top:
        cur.execute("SELECT source,path,line,txt FROM chunks WHERE id=?", (cid,))
        source, path, line, txt = cur.fetchall()[0]
        rel = os.path.relpath(path, HOME)
        snippet = textwrap.shorten(txt.replace("\n", " "), width=280, placeholder=" …")
        tag = "V+K" if cid in vec_ids and cid in fts_ids else ("V" if cid in vec_ids else "K")
        print(f"[{tag}] ~/{rel}:{line}\n    {snippet}\n")

def cmd_stats():
    con, cur = connect()
    cur.execute("SELECT COUNT(*),COUNT(DISTINCT path) FROM chunks")
    c, f = cur.fetchall()[0]
    sz = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    print(f"db={DB_PATH}\nfiles={f} chunks={c} size={sz/1024:.0f}KB")

# ---- cli --------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd_or_query")
    ap.add_argument("rest", nargs="*")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--hybrid", action="store_true",
                    help="use RRF hybrid (vector+keyword) instead of the default vector-only ranking")
    a = ap.parse_args()
    if a.cmd_or_query == "index":
        cmd_index(rebuild=a.rebuild)
    elif a.cmd_or_query == "stats":
        cmd_stats()
    else:
        cmd_recall(" ".join([a.cmd_or_query, *a.rest]), k=a.k, hybrid=a.hybrid)
