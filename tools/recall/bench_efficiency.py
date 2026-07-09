#!/usr/bin/env python3
"""
bench_efficiency.py — token-savings + latency for the recall POC.

Token model: ~chars/4 (standard rough estimate; labeled as estimate).
Savings: recall snippet output vs the baselines an agent would otherwise pay:
  (a) read the single full file the answer lives in
  (b) load the whole corpus into context (the "dump everything" upper bound)
Latency: end-to-end query time split into embed vs db-search, p50/p90.
Run from recall-poc dir.  python3 bench_efficiency.py
"""
import os, time, statistics, glob
import recall
# Queries come from the (gitignored) labeled set, so this file ships no
# personal query strings. Falls back to bench_labels.example.json if absent.
from bench_quality import LABELED

def toks(s): return max(1, len(s)//4)  # rough token estimate

QUERIES = [q for q, _ in LABELED[:8]]

def recall_output(cur, q, k=5):
    """Reproduce the snippet text recall prints (what lands in agent context)."""
    qv = str(recall.embed(q, is_query=True))
    cur.execute("SELECT id FROM chunks ORDER BY vector_distance_cos(emb, vector32(?)) LIMIT 20", (qv,))
    vec = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 20", (recall.fts_query(q),))
    fts = [r[0] for r in cur.fetchall()]
    sc = {}
    for r,i in enumerate(vec): sc[i]=sc.get(i,0)+1/(recall.RRF_K+r)
    for r,i in enumerate(fts): sc[i]=sc.get(i,0)+1/(recall.RRF_K+r)
    top = sorted(sc, key=sc.get, reverse=True)[:k]
    import textwrap
    out, paths = [], []
    for cid in top:
        cur.execute("SELECT path,line,txt FROM chunks WHERE id=?", (cid,))
        p,l,t = cur.fetchall()[0]; paths.append(p)
        out.append(f"~/{os.path.relpath(p, recall.HOME)}:{l}\n    " +
                   textwrap.shorten(t.replace(chr(10)," "), 280, placeholder=" …"))
    return "\n".join(out), paths

def main():
    con, cur = recall.connect()

    # ---- token savings ----
    corpus_tokens = 0
    for _, root in recall.SOURCES:
        for dp,dirs,files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in recall.EXCLUDE_DIRS]
            for f in files:
                if f.endswith(".md"):
                    corpus_tokens += toks(open(os.path.join(dp,f),encoding="utf-8",errors="replace").read())

    print(f"\n=== Token savings (est. tokens, ~chars/4) ===")
    print(f"whole-corpus 'dump everything' baseline: {corpus_tokens:,} tok")
    print(f"\n{'query':44} {'recall':>7} {'1 full file':>12} {'vs file':>8} {'vs corpus':>10}")
    rec_tot=ff_tot=0
    for q in QUERIES:
        out, paths = recall_output(cur, q)
        rt = toks(out)
        ft = toks(open(paths[0],encoding="utf-8",errors="replace").read()) if paths else 0
        rec_tot += rt; ff_tot += ft
        print(f"{q[:43]:44} {rt:>7} {ft:>12} {ft/rt:>7.1f}x {corpus_tokens/rt:>9.0f}x")
    n=len(QUERIES)
    print(f"\nmean recall output: {rec_tot//n} tok | mean single-file read: {ff_tot//n} tok")
    print(f"mean reduction vs single full file: {ff_tot/rec_tot:.1f}x | vs whole corpus: {corpus_tokens/(rec_tot/n):,.0f}x")

    # ---- latency ----
    print(f"\n=== Latency (end-to-end query) ===")
    emb_t, db_t, tot_t = [], [], []
    for q in QUERIES*2:  # 16 samples
        t0=time.perf_counter(); qv=str(recall.embed(q,is_query=True)); t1=time.perf_counter()
        cur.execute("SELECT id FROM chunks ORDER BY vector_distance_cos(emb,vector32(?)) LIMIT 20",(qv,)); cur.fetchall()
        cur.execute("SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 20",(recall.fts_query(q),)); cur.fetchall()
        t2=time.perf_counter()
        emb_t.append((t1-t0)*1000); db_t.append((t2-t1)*1000); tot_t.append((t2-t0)*1000)
    def pct(a,p): return sorted(a)[int(len(a)*p)]
    print(f"embed (ollama):   p50={statistics.median(emb_t):6.1f}ms  p90={pct(emb_t,.9):6.1f}ms")
    print(f"db search (both): p50={statistics.median(db_t):6.1f}ms  p90={pct(db_t,.9):6.1f}ms")
    print(f"end-to-end:       p50={statistics.median(tot_t):6.1f}ms  p90={pct(tot_t,.9):6.1f}ms")

    # ---- footprint ----
    sz = os.path.getsize(recall.DB_PATH)/1024/1024
    cur.execute("SELECT COUNT(*) FROM chunks"); nc=cur.fetchall()[0][0]
    print(f"\n=== Footprint ===")
    print(f"db size: {sz:.1f} MB for {nc} chunks  ({sz*1024/nc:.1f} KB/chunk)")

if __name__ == "__main__":
    main()
