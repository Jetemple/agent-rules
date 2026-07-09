#!/usr/bin/env python3
"""
recall — tool-agnostic semantic memory recall over a notes corpus + agent memory.

Engine : libSQL (native F32_BLOB vectors + brute-force vector_distance_cos) + FTS5.
Embed  : Ollama `embeddinggemma` (768-d, fully offline).
Recall : vector-only by default (see cmd_recall); --hybrid adds FTS5 + Reciprocal Rank
         Fusion, and FTS-only is the automatic fallback when the embedder is unreachable.

Usage:
  recall.py index            # incremental (only changed files) — run this before first query
  recall.py index --rebuild  # wipe + full reindex
  recall.py "query text"     # vector recall, prints file:line + snippet
  recall.py "query" --hybrid # RRF hybrid for noisier/larger corpora
  recall.py stats
Both Codex and Claude just shell out:  recall.py "how do I rebuild the index"
"""
import os, sys, json, hashlib, urllib.request, urllib.error, argparse, textwrap

# ---- venv bootstrap ---------------------------------------------------------
# libsql ships prebuilt wheels only for some CPython versions (3.13 here);
# the system python3 may lack it. If libsql isn't importable, re-exec this
# script under the project venv so the documented `python3 recall.py` path
# works from any runtime (Claude, Codex, plain shell) without a wrapper.
def _ensure_libsql():
    try:
        import libsql  # noqa: F401
        return
    except ImportError:
        venv_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".venv", "bin", "python3")
        if os.path.exists(venv_py) and os.path.realpath(sys.executable) != os.path.realpath(venv_py):
            os.execv(venv_py, [venv_py, os.path.abspath(__file__), *sys.argv[1:]])
        raise
_ensure_libsql()

# ---- config -----------------------------------------------------------------
HOME      = os.path.expanduser("~")
DB_PATH   = os.path.join(HOME, ".recall", "memory.db")
OLLAMA    = "http://localhost:11434/api/embeddings"
MODEL     = "embeddinggemma:300m"
DIM       = 768
CHUNK_MAX = 1100          # chars per chunk (soft)
RRF_K     = 60            # reciprocal-rank-fusion constant

# Corpus config is loaded at runtime, never hardcoded, so this file can be
# shared/published without leaking personal paths. Priority order:
#   1. ~/.recall/config.json  (gitignored; the owner's real paths)
#   2. RECALL_SOURCES env var  (JSON: [{"label":..,"path":..}, ...])
#   3. a generic built-in default (+ a one-line hint to create config.json)
# Copy config.example.json -> config.json and edit it to point at your corpus.
CONFIG_PATH = os.path.join(HOME, ".recall", "config.json")
DEFAULT_SOURCES = [
    ("memory", os.path.join(HOME, "notes", "memory")),
    ("vault",  os.path.join(HOME, "notes", "vault")),
]

def _parse_sources(obj):
    """Turn a {"sources":[{"label","path"}]} JSON object into [(label, path)]."""
    out = []
    for s in obj.get("sources", []):
        label = s.get("label")
        path = s.get("path")
        if label and path:
            out.append((label, os.path.expanduser(path)))
    return out

def load_sources():
    # 1. config.json
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                src = _parse_sources(json.load(f))
            if src:
                return src
        except (json.JSONDecodeError, OSError) as e:
            print(f"recall: could not read {CONFIG_PATH}: {e}", file=sys.stderr)
    # 2. RECALL_SOURCES env var
    env = os.environ.get("RECALL_SOURCES")
    if env:
        try:
            src = _parse_sources(json.loads(env))
            if src:
                return src
        except json.JSONDecodeError as e:
            print(f"recall: could not parse RECALL_SOURCES: {e}", file=sys.stderr)
    # 3. generic default + hint
    print(f"recall: no config found; using placeholder paths. "
          f"Create {CONFIG_PATH} (copy config.example.json) to point at your corpus.",
          file=sys.stderr)
    return [(label, os.path.expanduser(path)) for label, path in DEFAULT_SOURCES]

SOURCES = load_sources()
# Hard constitution rules: never index these.
EXCLUDE_DIRS = {"_scratch", "_archive", ".git", "node_modules", ".obsidian"}

# ---- embedding --------------------------------------------------------------
def embed(text, is_query, _tries=5):
    # EmbeddingGemma documented retrieval prompts
    prompt = (f"task: search result | query: {text}" if is_query
              else f"title: none | text: {text}")
    body = json.dumps({"model": MODEL, "prompt": prompt}).encode()
    for attempt in range(_tries):
        try:
            req = urllib.request.Request(OLLAMA, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["embedding"]
        except (urllib.error.URLError, ConnectionError, OSError) as e:
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
def connect():
    import libsql
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = libsql.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS chunks(
        id INTEGER PRIMARY KEY, source TEXT, path TEXT, line INTEGER,
        txt TEXT, emb F32_BLOB({DIM}))""")
    # No ANN index: corpus is small (<10k chunks), so a brute-force
    # vector_distance_cos scan is exact, sub-ms, and keeps the DB ~5MB
    # instead of ~155MB (DiskANN stores ~50 raw neighbor vectors/node).
    cur.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS fts
        USING fts5(txt, content='chunks', content_rowid='id')""")
    cur.execute("""CREATE TABLE IF NOT EXISTS files(
        path TEXT PRIMARY KEY, hash TEXT)""")
    con.commit()
    return con, cur

def iter_files():
    for source, root in SOURCES:
        if not os.path.isdir(root):
            continue
        for dp, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f.endswith(".md"):
                    yield source, os.path.join(dp, f)

# ---- commands ---------------------------------------------------------------
def cmd_index(rebuild=False):
    con, cur = connect()
    if rebuild:
        cur.execute("INSERT INTO fts(fts) VALUES('delete-all')")
        cur.execute("DELETE FROM chunks")
        cur.execute("DELETE FROM files")
        con.commit()
    seen, changed, n_chunks = set(), 0, 0
    for source, path in iter_files():
        seen.add(path)
        raw = open(path, encoding="utf-8", errors="replace").read()
        h = hashlib.sha1(raw.encode()).hexdigest()
        cur.execute("SELECT hash FROM files WHERE path=?", (path,))
        row = cur.fetchall()
        if row and row[0][0] == h:
            continue                       # unchanged -> skip (incremental)
        changed += 1
        # purge old chunks for this file
        cur.execute("SELECT id FROM chunks WHERE path=?", (path,))
        for (cid,) in cur.fetchall():
            cur.execute("DELETE FROM fts WHERE rowid=?", (cid,))
        cur.execute("DELETE FROM chunks WHERE path=?", (path,))
        for start, body in chunk_md(raw):
            v = embed(body, is_query=False)
            cur.execute(
                "INSERT INTO chunks(source,path,line,txt,emb) VALUES (?,?,?,?,vector32(?))",
                (source, path, start, body, str(v)))
            cid = cur.lastrowid
            cur.execute("INSERT INTO fts(rowid,txt) VALUES (?,?)", (cid, body))
            n_chunks += 1
        cur.execute("INSERT OR REPLACE INTO files(path,hash) VALUES (?,?)", (path, h))
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
    con.commit()
    print(f"done. {changed} files changed, {n_chunks} chunks (re)embedded.", file=sys.stderr)

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
    # If Ollama is down/unreachable, degrade to FTS-only instead of crashing.
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
