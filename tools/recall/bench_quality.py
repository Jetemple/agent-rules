#!/usr/bin/env python3
"""
bench_quality.py — retrieval-quality ablation for the recall POC.
Compares hybrid (RRF) vs vector-only vs keyword-only(FTS) on a labeled set.
Metrics: hit@1, hit@3, hit@5, MRR (mean reciprocal rank of first correct hit).
Run from the recall-poc dir.  python3 bench_quality.py [--k 5]
"""
import os, sys, json, argparse
import recall  # reuse embed(), connect(), fts_query(), RRF_K

POOL = 20

# Labeled queries are loaded from JSON, never hardcoded, so this file can be
# shared/published without leaking personal queries/notes. Priority order:
#   1. ~/.recall/bench_labels.json  (gitignored; the owner's real labels)
#   2. bench_labels.example.json    (tracked; generic placeholders)
# Each JSON entry is [query, expected_path_substring]; loaded as a 2-tuple.
HERE = os.path.dirname(os.path.abspath(__file__))
LABELS_REAL = os.path.join(os.path.expanduser("~"), ".recall", "bench_labels.json")
LABELS_EXAMPLE = os.path.join(HERE, "bench_labels.example.json")

def load_labeled():
    path = LABELS_REAL if os.path.exists(LABELS_REAL) else LABELS_EXAMPLE
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # data: list of [query, expected]; normalize to list of (query, expected) tuples
    return [tuple(pair) for pair in data]

# (query, expected path substring that identifies the correct note)
LABELED = load_labeled()

def rank_vector(cur, q, n=POOL):
    qv = str(recall.embed(q, is_query=True))
    cur.execute("SELECT id,path FROM chunks ORDER BY vector_distance_cos(emb, vector32(?)) LIMIT ?", (qv, n))
    return cur.fetchall()  # [(id,path)] ordered

def rank_fts(cur, q, n=POOL):
    cur.execute("SELECT c.id,c.path FROM fts JOIN chunks c ON c.id=fts.rowid WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                (recall.fts_query(q), n))
    return cur.fetchall()

def rank_hybrid(cur, q, n=POOL):
    vec = rank_vector(cur, q, n)
    fts = rank_fts(cur, q, n)
    pathof = {i: p for i, p in vec + fts}
    scores = {}
    for r, (i, _) in enumerate(vec): scores[i] = scores.get(i, 0) + 1.0/(recall.RRF_K + r)
    for r, (i, _) in enumerate(fts): scores[i] = scores.get(i, 0) + 1.0/(recall.RRF_K + r)
    order = sorted(scores, key=scores.get, reverse=True)
    return [(i, pathof[i]) for i in order]

MODES = {"hybrid": rank_hybrid, "vector": rank_vector, "fts": rank_fts}

def first_hit_rank(ranked, expected):
    for idx, (_, path) in enumerate(ranked, 1):
        if expected in path:
            return idx
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--json", action="store_true"); a = ap.parse_args()
    con, cur = recall.connect()
    results = {m: {"hit@1":0,"hit@3":0,"hit@5":0,"mrr":0.0,"misses":[]} for m in MODES}
    detail = []
    for q, exp in LABELED:
        row = {"query": q, "expected": exp}
        for m, fn in MODES.items():
            r = first_hit_rank(fn(cur, q), exp)
            row[m] = r
            R = results[m]
            if r:
                if r <= 1: R["hit@1"] += 1
                if r <= 3: R["hit@3"] += 1
                if r <= 5: R["hit@5"] += 1
                R["mrr"] += 1.0/r
            else:
                R["misses"].append((q, exp))
        detail.append(row)
    n = len(LABELED)
    for m in MODES: results[m]["mrr"] = round(results[m]["mrr"]/n, 3)

    if a.json:
        print(json.dumps({"n":n,"results":results,"detail":detail}, indent=2)); return
    print(f"\n=== Retrieval quality over {n} labeled queries (pool={POOL}) ===")
    print(f"{'mode':8} {'hit@1':>7} {'hit@3':>7} {'hit@5':>7} {'MRR':>7}")
    for m in ("hybrid","vector","fts"):
        R = results[m]
        print(f"{m:8} {R['hit@1']:>5}/{n} {R['hit@3']:>5}/{n} {R['hit@5']:>5}/{n} {R['mrr']:>7}")
    print("\n=== per-query first-hit rank (lower=better, '-'=miss in top20) ===")
    print(f"{'expected':34} {'hyb':>4} {'vec':>4} {'fts':>4}  query")
    for d in detail:
        f = lambda v: str(v) if v else "-"
        print(f"{d['expected'][:33]:34} {f(d['hybrid']):>4} {f(d['vector']):>4} {f(d['fts']):>4}  {d['query'][:42]}")

if __name__ == "__main__":
    main()
