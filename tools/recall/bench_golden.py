#!/usr/bin/env python3
"""
bench_golden.py — golden retrieval tests for recall.

bench_quality.py answers "which mode wins on a handful of labels". This answers
"did retrieval get worse" and "is configuration B better than A" on a labeled set
that is varied enough to trust:

  * several acceptable targets per query, optionally pinned to a passage
  * "avoid" targets: the stale or similar-but-wrong note that must not outrank
    the right one
  * no-answer queries: nothing in the corpus is relevant, so the useful signal is
    whether a confidence score separates them from answerable queries
  * a frozen snapshot, so two runs differ only in what you changed
  * a saved baseline and a gate that exits non-zero on regression

Cases are loaded from JSON Lines, never hardcoded, so this file can be published
without leaking personal queries. Priority order:
  1. --cases / $RECALL_GOLDEN_CASES
  2. ~/.recall/golden/cases.jsonl     (private; the owner's real cases)
  3. golden_cases.example.jsonl       (tracked; generic placeholders)

One case per line:
  {"id": "deploy-1", "query": "how do I ship to staging", "type": "paraphrase",
   "origin": "authored", "status": "golden", "tags": ["must"],
   "expect": [{"path": "notes/deploy_runbook.md", "passage": "kubectl rollout", "grade": 2}],
   "avoid":  [{"path": "notes/deploy_runbook_2023.md", "why": "superseded"}]}
`path` is a substring of the printed citation (source/rel). `passage` is optional
text that must appear in the returned chunk. A `no_answer` case has an empty
`expect`. Only `golden` cases are gated; `candidate` cases are scored separately.

Usage:
  bench_golden.py lint                      # label health against the index
  bench_golden.py freeze                    # copy the DB to an immutable snapshot
  bench_golden.py run [--db SNAP] [--save-baseline]
  bench_golden.py check [--db SNAP]         # run, compare to the baseline, exit 1 on regression
  bench_golden.py compare A.json B.json     # paired A/B for an embedder or ranker bake-off
  bench_golden.py reembed --db SNAP --out COPY --embed-model M   # build the B side of a bake-off

Exit codes: 0 ok, 1 regression (check) or failed gate (compare --gate),
2 label-health errors, 3 environment (database or embedder unavailable).
"""
import argparse, hashlib, json, math, os, random, shutil, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
GOLDEN_HOME = os.path.join(HOME, ".recall", "golden")
CASES_REAL = os.path.join(GOLDEN_HOME, "cases.jsonl")
CASES_EXAMPLE = os.path.join(HERE, "golden_cases.example.jsonl")
BASELINE = os.path.join(GOLDEN_HOME, "baseline.json")

MODES = ("hybrid", "vector", "fts")
STATUSES = ("golden", "candidate", "review", "retired")
TYPES = ("known_item", "paraphrase", "keyword", "distractor", "stale_current",
         "long_page", "multi_target", "no_answer")
POOL = 20            # per-arm candidate pool; matches the engine's recall default
NDCG_K = 10

# Regression gate, declared here so a run cannot pick its own bar after seeing
# the numbers. `check` fails when the gated mode loses more than this against the
# baseline, or when any case tagged "must" falls out of the top MUST_RANK.
GATE_MODE = "hybrid"
TOL_MRR = 0.02       # absolute MRR drop tolerated (corpus drift on a live index)
TOL_HIT3 = 0.02      # fraction of compared cases allowed to leave the top 3
MUST_RANK = 3
# Bake-off gate for `compare --gate`: B replaces A only if it wins on every one
# of these modes, by at least MIN_GAIN in MRR, with more wins than losses.
BAKEOFF_MODES = ("vector", "hybrid")
MIN_GAIN = 0.01

EXIT_REGRESSION, EXIT_LABELS, EXIT_ENV = 1, 2, 3


# ---- cases ------------------------------------------------------------------
def cases_path(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("RECALL_GOLDEN_CASES")
    if env:
        return os.path.expanduser(env)
    return CASES_REAL if os.path.exists(CASES_REAL) else CASES_EXAMPLE


def load_cases(path):
    """Parse a JSON Lines case file. Blank lines and `#` comments are skipped.
    Shape problems raise ValueError with the line number; nothing is guessed."""
    cases = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number}: not valid JSON ({error.msg})") from error
            if not isinstance(case, dict):
                raise ValueError(f"{path}:{number}: a case must be a JSON object")
            for field in ("id", "query"):
                if not isinstance(case.get(field), str) or not case[field].strip():
                    raise ValueError(f"{path}:{number}: missing {field!r}")
            case.setdefault("type", "known_item")
            case.setdefault("origin", "authored")
            case.setdefault("status", "golden")
            case.setdefault("tags", [])
            for field in ("expect", "avoid"):
                targets = case.setdefault(field, [])
                if not isinstance(targets, list) or not all(
                        isinstance(t, dict) and isinstance(t.get("path"), str) and t["path"]
                        for t in targets):
                    raise ValueError(f"{path}:{number}: {field!r} must be a list of {{path: ...}}")
            case["_line"] = number
            cases.append(case)
    return cases


def signature(case):
    """Identity of what a case asserts. A baseline row is only comparable to a
    current row when the query and its labels are unchanged."""
    body = json.dumps([case["query"], case.get("expect", []), case.get("avoid", []),
                       case.get("type")], sort_keys=True)
    return hashlib.sha1(body.encode()).hexdigest()[:12]


def norm(text):
    return " ".join((text or "").lower().split())


# ---- index access -----------------------------------------------------------
def load_engine(db=None, embed_url=None, embed_model=None):
    """Import the engine with per-run overrides. The engine reads its config at
    import time and env vars beat config.json, so the overrides are set first.
    Always read-only: a benchmark must never be able to write the index."""
    if db:
        os.environ["RECALL_DB"] = db
    os.environ["RECALL_READONLY"] = "1"
    if embed_url:
        os.environ["RECALL_EMBED_URL"] = embed_url
    if embed_model:
        os.environ["RECALL_EMBED_MODEL"] = embed_model
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import recall
    return recall


class Index:
    """The corpus as the engine sees it, loaded once. Ranking goes through the
    engine's own embed/FTS/RRF code so the numbers describe production."""

    def __init__(self, engine, pool=POOL):
        self.engine = engine
        self.pool = pool
        self.con, self.cur = engine.connect(read_only=True)
        rel = "rel" if engine._chunks_has_rel(self.cur) else "NULL AS rel"
        self.cur.execute(f"SELECT id,source,path,{rel},line,txt FROM chunks ORDER BY id")
        self.chunks = {}
        for cid, source, path, rel_path, line, txt in self.cur.fetchall():
            self.chunks[cid] = {"id": cid, "cite": engine._citation(source, path, rel_path),
                                "path": path, "line": line, "txt": norm(txt)}
        self.files = sorted({c["cite"] for c in self.chunks.values()})

    def fingerprint(self):
        """Hash of the indexed text, independent of the vectors. Two databases
        with the same fingerprint hold the same corpus, so a re-embedded copy is
        a like-for-like comparison and a reindexed one is not."""
        digest = hashlib.sha256()
        for chunk in sorted(self.chunks.values(), key=lambda c: (c["cite"], c["line"], c["id"])):
            digest.update(f"{chunk['cite']}\0{chunk['line']}\0".encode())
            digest.update(hashlib.sha1(chunk["txt"].encode()).digest())
        return digest.hexdigest()[:16]

    def embed_model(self):
        """Model recorded by `reembed` in a bake-off copy, else None."""
        try:
            self.cur.execute("SELECT value FROM bench_meta WHERE key='embed_model'")
            row = self.cur.fetchall()
            return row[0][0] if row else None
        except Exception:
            return None

    def vector(self, query):
        t0 = time.perf_counter()
        qv = str(self.engine.embed(query, is_query=True))
        t1 = time.perf_counter()
        self.cur.execute("""SELECT id, vector_distance_cos(emb, vector32(?)) AS d
                            FROM chunks ORDER BY d LIMIT ?""", (qv, self.pool))
        rows = self.cur.fetchall()
        t2 = time.perf_counter()
        return [r[0] for r in rows], [r[1] for r in rows], (t1 - t0) * 1000, (t2 - t1) * 1000

    def fts(self, query):
        t0 = time.perf_counter()
        ids = self.engine._fts_ids(self.cur, query, self.pool)
        return ids, (time.perf_counter() - t0) * 1000


def fuse(vec_ids, fts_ids, rrf_k):
    """Reciprocal rank fusion, the same arithmetic and tie order as the engine."""
    scores = {}
    for rank, cid in enumerate(vec_ids):
        scores[cid] = scores.get(cid, 0) + 1.0 / (rrf_k + rank)
    for rank, cid in enumerate(fts_ids):
        scores[cid] = scores.get(cid, 0) + 1.0 / (rrf_k + rank)
    return sorted(scores, key=scores.get, reverse=True), scores


# ---- scoring (pure; no index or embedder needed) ----------------------------
def path_matches(want, chunk):
    return want in chunk["cite"] or want in chunk["path"]


def first_rank(ranked, targets, need_passage=False):
    """1-based rank of the first chunk matching any target, else None. With
    need_passage, only targets that pin a passage count and the chunk must
    contain it: the right file but the wrong section is a miss."""
    for position, chunk in enumerate(ranked, 1):
        for target in targets:
            passage = target.get("passage")
            if need_passage and not passage:
                continue
            if not path_matches(target["path"], chunk):
                continue
            if need_passage and norm(passage) not in chunk["txt"]:
                continue
            return position
    return None


def ndcg(ranked, targets, k=NDCG_K):
    """Graded nDCG@k at file level: each expected file earns its grade once, at
    its first appearance, so ten chunks of one long page cannot inflate it."""
    if not targets:
        return None
    grades = [float(t.get("grade", 1)) for t in targets]
    earned, dcg = set(), 0.0
    for position, chunk in enumerate(ranked[:k], 1):
        for index, target in enumerate(targets):
            if index not in earned and path_matches(target["path"], chunk):
                earned.add(index)
                dcg += grades[index] / math.log2(position + 1)
                break
    ideal = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(grades, reverse=True)[:k]))
    return dcg / ideal if ideal else None


def score_case(case, ranked):
    expect, avoid = case["expect"], case["avoid"]
    has_passage = any(t.get("passage") for t in expect)
    return {
        "file": first_rank(ranked, expect) if expect else None,
        "passage": first_rank(ranked, expect, need_passage=True) if has_passage else None,
        "avoid": first_rank(ranked, avoid) if avoid else None,
        "ndcg": ndcg(ranked, expect),
    }


def auroc(positives, negatives):
    """P(score of an answerable query > score of a no-answer query); ties count
    half. 0.5 means the score cannot tell them apart."""
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def fpr_at_tpr(positives, negatives, tpr=0.95):
    """Pick the threshold that still keeps `tpr` of answerable queries, then
    report how many no-answer queries clear it. This is the false-alarm rate a
    min-score cutoff would have at that recall."""
    if not positives or not negatives:
        return None, None
    ordered = sorted(positives)
    threshold = ordered[min(len(ordered) - 1, int(math.floor((1 - tpr) * len(ordered))))]
    return sum(n >= threshold for n in negatives) / len(negatives), threshold


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def summarize(rows, mode):
    """Aggregate answerable rows for one mode. Counts, not rates, so a reader can
    see the denominator."""
    answerable = [r for r in rows if r["type"] != "no_answer"]
    ranks = [r["ranks"][mode]["file"] for r in answerable]
    out = {"n": len(answerable)}
    for k in (1, 3, 5, 10):
        out[f"hit@{k}"] = sum(1 for r in ranks if r and r <= k)
    out["mrr"] = round(sum(1.0 / r for r in ranks if r) / len(ranks), 4) if ranks else None
    gains = [r["ranks"][mode]["ndcg"] for r in answerable if r["ranks"][mode]["ndcg"] is not None]
    out["ndcg@10"] = round(sum(gains) / len(gains), 4) if gains else None
    pinned = [r for r in answerable if r["has_passage"]]
    p_ranks = [r["ranks"][mode]["passage"] for r in pinned]
    out["passage"] = {"n": len(pinned),
                      "hit@1": sum(1 for r in p_ranks if r and r <= 1),
                      "hit@3": sum(1 for r in p_ranks if r and r <= 3),
                      "hit@5": sum(1 for r in p_ranks if r and r <= 5),
                      "mrr": round(sum(1.0 / r for r in p_ranks if r) / len(p_ranks), 4) if p_ranks else None}
    # An avoid target "wins" when it outranks every expected target, including
    # when nothing expected was retrieved at all.
    guarded = [r for r in rows if r["has_avoid"]]
    above = [r for r in guarded
             if r["ranks"][mode]["avoid"] and (not r["ranks"][mode]["file"]
                                               or r["ranks"][mode]["avoid"] < r["ranks"][mode]["file"])]
    out["avoid"] = {"n": len(guarded), "above_expected": len(above),
                    "at_rank_1": sum(1 for r in guarded if r["ranks"][mode]["avoid"] == 1)}
    return out


def breakdown(rows, mode, key):
    groups = {}
    for row in rows:
        if row["type"] == "no_answer":
            continue
        values = row[key] if isinstance(row[key], list) else [row[key]]
        for value in values:
            groups.setdefault(value, []).append(row["ranks"][mode]["file"])
    table = {}
    for value, ranks in sorted(groups.items()):
        table[value] = {"n": len(ranks),
                        "hit@1": sum(1 for r in ranks if r and r <= 1),
                        "hit@3": sum(1 for r in ranks if r and r <= 3),
                        "mrr": round(sum(1.0 / r for r in ranks if r) / len(ranks), 3)}
    return table


def abstention(rows):
    """How well two cheap confidence scores separate answerable queries from
    no-answer ones. The engine returns k results for anything; this measures
    whether a cutoff could be added without throwing away real answers."""
    out = {}
    for name in ("sim", "rrf"):
        positives = [r[name] for r in rows if r["type"] != "no_answer" and r[name] is not None]
        negatives = [r[name] for r in rows if r["type"] == "no_answer" and r[name] is not None]
        area = auroc(positives, negatives)
        false_alarms, threshold = fpr_at_tpr(positives, negatives)
        out[name] = {"answerable": len(positives), "no_answer": len(negatives),
                     "auroc": round(area, 4) if area is not None else None,
                     "fpr_at_tpr95": round(false_alarms, 4) if false_alarms is not None else None,
                     "threshold": round(threshold, 4) if threshold is not None else None}
    return out


# ---- label health -----------------------------------------------------------
def lint_cases(cases, files, chunks):
    """Check labels against the index. Errors make a case unusable (it would
    score as a miss for a reason that is not retrieval); warnings are advisory."""
    problems = []

    def add(level, case, code, detail):
        problems.append({"level": level, "id": case["id"], "code": code, "detail": detail})

    seen_ids, seen_queries = {}, {}
    for case in cases:
        if case["id"] in seen_ids:
            add("error", case, "duplicate_id", f"also on line {seen_ids[case['id']]}")
        seen_ids[case["id"]] = case["_line"]
        if case["status"] not in STATUSES:
            add("error", case, "bad_status", case["status"])
        if case["type"] not in TYPES:
            add("warn", case, "unknown_type", case["type"])
        if case["status"] in ("retired", "review"):
            continue
        key = norm(case["query"])
        if key in seen_queries:
            add("warn", case, "duplicate_query", f"same query as {seen_queries[key]}")
        seen_queries[key] = case["id"]
        if case["type"] == "no_answer" and case["expect"]:
            add("error", case, "no_answer_has_expect", "a no_answer case must have an empty expect")
        if case["type"] != "no_answer" and not case["expect"]:
            add("error", case, "empty_expect", "an answerable case needs at least one expect target")
        for target in case["expect"]:
            matched = [f for f in files if target["path"] in f]
            if not matched:
                add("error", case, "stale_path", f"{target['path']} is not in the index")
                continue
            if len(matched) > 1 and target["path"].endswith(".md"):
                add("warn", case, "ambiguous_path",
                    f"{target['path']} matches {len(matched)} files, e.g. {matched[0]}, {matched[1]}")
            passage = target.get("passage")
            if passage and not any(norm(passage) in c["txt"] for c in chunks
                                   if target["path"] in c["cite"]):
                add("error", case, "stale_passage",
                    f"passage not found in {target['path']}: {passage[:60]!r}")
        for target in case["avoid"]:
            if not any(target["path"] in f for f in files):
                add("warn", case, "stale_avoid", f"{target['path']} is not in the index")
    return problems


def unusable(problems):
    return {p["id"] for p in problems if p["level"] == "error"}


# ---- run --------------------------------------------------------------------
def file_sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate(index, cases, modes=MODES, show=5):
    need_vector = any(m in modes for m in ("hybrid", "vector"))
    rows = []
    for case in cases:
        vec_ids, dists, embed_ms, vec_ms = index.vector(case["query"]) if need_vector else ([], [], 0, 0)
        fts_ids, fts_ms = index.fts(case["query"])
        fused, scores = fuse(vec_ids, fts_ids, index.engine.RRF_K)
        ordered = {"hybrid": fused, "vector": vec_ids, "fts": fts_ids}
        row = {"id": case["id"], "sig": signature(case), "query": case["query"],
               "type": case["type"], "origin": case["origin"], "status": case["status"],
               "tags": case["tags"], "has_passage": any(t.get("passage") for t in case["expect"]),
               "has_avoid": bool(case["avoid"]),
               "sim": round(1 - dists[0], 5) if dists else None,
               "rrf": round(scores[fused[0]], 6) if fused else 0.0,
               "ms": {"embed": round(embed_ms, 1), "vector": round(vec_ms, 1), "fts": round(fts_ms, 1)},
               "ranks": {}, "top": {}}
        for mode in modes:
            ranked = [index.chunks[cid] for cid in ordered[mode] if cid in index.chunks]
            row["ranks"][mode] = score_case(case, ranked)
            row["top"][mode] = [f"{c['cite']}:{c['line']}" for c in ranked[:show]]
        rows.append(row)
    return rows


def build_report(rows, problems, meta, modes=MODES):
    golden = [r for r in rows if r["status"] == "golden"]
    candidate = [r for r in rows if r["status"] == "candidate"]
    report = {"meta": meta, "label_health": problems, "summary": {}, "candidates": {},
              "by_type": {}, "by_origin": {}, "abstention": abstention(golden), "latency_ms": {},
              "cases": rows}
    for mode in modes:
        report["summary"][mode] = summarize(golden, mode)
        if candidate:
            report["candidates"][mode] = summarize(candidate, mode)
        report["by_type"][mode] = breakdown(golden, mode, "type")
        report["by_origin"][mode] = breakdown(golden, mode, "origin")
    for part in ("embed", "vector", "fts"):
        values = [r["ms"][part] for r in rows]
        report["latency_ms"][part] = {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95)}
    return report


def run(args):
    path = cases_path(args.cases)
    try:
        cases = load_cases(path)
    except (OSError, ValueError) as error:
        print(f"bench_golden: {error}", file=sys.stderr)
        raise SystemExit(EXIT_LABELS)
    modes = tuple(m for m in MODES if m in args.modes.split(","))
    try:
        engine = load_engine(args.db, args.embed_url, args.embed_model)
        index = Index(engine, pool=args.pool)
    except Exception as error:
        print(f"bench_golden: cannot open the index ({error})", file=sys.stderr)
        raise SystemExit(EXIT_ENV)
    # A re-embedded copy records its model. Querying it with another model's
    # vectors would produce confident nonsense, so refuse rather than guess.
    recorded = index.embed_model()
    if recorded and recorded != engine.MODEL:
        if args.embed_model:
            print(f"bench_golden: {engine.DB_PATH} was embedded with {recorded}, "
                  f"not {args.embed_model}", file=sys.stderr)
            raise SystemExit(EXIT_ENV)
        engine.MODEL = recorded
    if any(m in modes for m in ("hybrid", "vector")):
        try:
            # One attempt, no backoff: a down embedder should stop the run now,
            # not after every case has waited out the engine's retries.
            engine.embed("bench_golden preflight", is_query=True, _tries=1)
        except Exception as error:
            print(f"bench_golden: embedder unavailable at {engine.EMBED_URL} "
                  f"({type(error).__name__}: {error})", file=sys.stderr)
            raise SystemExit(EXIT_ENV)
    problems = lint_cases(cases, index.files, list(index.chunks.values()))
    broken = unusable(problems)
    active = [c for c in cases if c["status"] in ("golden", "candidate") and c["id"] not in broken]
    try:
        rows = evaluate(index, active, modes, show=args.k)
    except Exception as error:
        # No silent keyword-only fallback: a degraded run must not look like a
        # result. The engine's own fallback is for serving, not for measuring.
        print(f"bench_golden: retrieval failed, run aborted ({type(error).__name__}: {error})",
              file=sys.stderr)
        raise SystemExit(EXIT_ENV)
    meta = {"when": datetime.now().astimezone().isoformat(timespec="seconds"),
            "tag": args.tag, "db": engine.DB_PATH, "db_sha256": file_sha(engine.DB_PATH)[:16],
            "corpus": index.fingerprint(), "chunks": len(index.chunks), "files": len(index.files),
            "embed_model": engine.MODEL, "rrf_k": engine.RRF_K, "pool": args.pool,
            "cases_file": path, "cases_sha256": file_sha(path)[:16],
            "n_cases": len(cases), "n_scored": len(rows), "modes": list(modes)}
    return build_report(rows, problems, meta, modes), broken


def print_report(report, verbose=False):
    meta = report["meta"]
    print(f"\n=== golden retrieval: {meta['n_scored']} cases scored of {meta['n_cases']} "
          f"| {meta['chunks']} chunks / {meta['files']} files | {meta['embed_model']} ===")
    print(f"db {meta['db_sha256']}  corpus {meta['corpus']}  cases {meta['cases_sha256']}")
    print(f"\n{'mode':8} {'n':>4} {'hit@1':>6} {'hit@3':>6} {'hit@5':>6} {'hit@10':>6} {'MRR':>7} {'nDCG@10':>8}"
          f" | {'passage@3':>10} | {'avoid above':>11}")
    for mode, s in report["summary"].items():
        p, a = s["passage"], s["avoid"]
        print(f"{mode:8} {s['n']:>4} {s['hit@1']:>6} {s['hit@3']:>6} {s['hit@5']:>6} {s['hit@10']:>6} "
              f"{s['mrr'] if s['mrr'] is not None else '-':>7} "
              f"{s['ndcg@10'] if s['ndcg@10'] is not None else '-':>8}"
              f" | {str(p['hit@3']) + '/' + str(p['n']):>10} | {str(a['above_expected']) + '/' + str(a['n']):>11}")
    if report["candidates"]:
        print("\ncandidates (scored, not gated)")
        for mode, s in report["candidates"].items():
            print(f"{mode:8} {s['n']:>4} {s['hit@1']:>6} {s['hit@3']:>6} {s['hit@5']:>6} {s['hit@10']:>6} {s['mrr']:>7}")
    for title, key in (("by type", "by_type"), ("by origin", "by_origin")):
        table = report[key].get(GATE_MODE) or next(iter(report[key].values()), {})
        if table:
            print(f"\n{title} ({GATE_MODE if GATE_MODE in report[key] else 'first mode'})")
            for value, s in table.items():
                print(f"  {value:22} n={s['n']:<4} hit@1 {s['hit@1']:>3}  hit@3 {s['hit@3']:>3}  MRR {s['mrr']}")
    ab = report["abstention"]
    if ab["sim"]["no_answer"]:
        print("\nno-answer separation (can a cutoff tell 'nothing relevant' from a real answer?)")
        for name, label in (("sim", "top-1 cosine"), ("rrf", "top-1 RRF")):
            s = ab[name]
            print(f"  {label:13} AUROC {s['auroc']}  false alarms at 95% recall: {s['fpr_at_tpr95']} "
                  f"(threshold {s['threshold']}, {s['no_answer']} no-answer cases)")
    lat = report["latency_ms"]
    print(f"\nlatency ms p50/p95: embed {lat['embed']['p50']}/{lat['embed']['p95']}  "
          f"vector {lat['vector']['p50']}/{lat['vector']['p95']}  fts {lat['fts']['p50']}/{lat['fts']['p95']}")
    errors = [p for p in report["label_health"] if p["level"] == "error"]
    warns = [p for p in report["label_health"] if p["level"] == "warn"]
    print(f"\nlabel health: {len(errors)} errors, {len(warns)} warnings")
    for problem in errors + (warns if verbose else []):
        print(f"  {problem['level']:5} {problem['id']:18} {problem['code']:20} {problem['detail']}")
    mode = GATE_MODE if GATE_MODE in report["summary"] else next(iter(report["summary"]))
    missed = [r for r in report["cases"] if r["status"] == "golden" and r["type"] != "no_answer"
              and not (r["ranks"][mode]["file"] and r["ranks"][mode]["file"] <= 5)]
    print(f"\n{mode} misses outside the top 5: {len(missed)}")
    for row in missed if verbose else missed[:15]:
        rank = row["ranks"][mode]["file"] or "-"
        print(f"  {row['id']:18} rank {rank!s:>3}  {row['query'][:70]}")
    if len(missed) > 15 and not verbose:
        print(f"  ... {len(missed) - 15} more (use -v)")


def save_report(report, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)


def cmd_run(args):
    report, broken = run(args)
    out = args.out or os.path.join(
        GOLDEN_HOME, "runs", f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{args.tag}.json")
    save_report(report, out)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print_report(report, args.verbose)
        print(f"\nsaved {out}")
    if args.save_baseline:
        if broken:
            print("bench_golden: refusing to save a baseline while labels have errors", file=sys.stderr)
            raise SystemExit(EXIT_LABELS)
        save_report(report, args.baseline)
        print(f"baseline written to {args.baseline}")
    if broken and not args.allow_stale:
        raise SystemExit(EXIT_LABELS)


# ---- check: regression gate -------------------------------------------------
def gate(baseline, current, mode=GATE_MODE, strict=False):
    """Compare the cases both runs share, unchanged. Returns (failures, notes,
    changes). Cases added, removed, or relabeled since the baseline are reported
    and left out, so growing the set never trips or hides a regression."""
    base = {r["sig"]: r for r in baseline["cases"] if r["status"] == "golden" and r["type"] != "no_answer"}
    now = {r["sig"]: r for r in current["cases"] if r["status"] == "golden" and r["type"] != "no_answer"}
    shared = [s for s in base if s in now]
    failures, changes = [], []
    notes = [f"{len(shared)} cases compared; {len(now) - len(shared)} new or relabeled; "
             f"{len(base) - len(shared)} gone from the current set"]
    if not shared:
        return ["no comparable cases: the baseline shares nothing with the current set"], notes, changes

    def rank(row, m=mode):
        return row["ranks"].get(m, {}).get("file")

    def mrr(rows):
        return sum(1.0 / rank(r) for r in rows if rank(r)) / len(rows)

    before, after = [base[s] for s in shared], [now[s] for s in shared]
    drop = mrr(before) - mrr(after)
    left_top3 = [s for s in shared if rank(base[s]) and rank(base[s]) <= 3
                 and not (rank(now[s]) and rank(now[s]) <= 3)]
    entered_top3 = [s for s in shared if rank(now[s]) and rank(now[s]) <= 3
                    and not (rank(base[s]) and rank(base[s]) <= 3)]
    for s in shared:
        if rank(base[s]) != rank(now[s]):
            changes.append({"id": now[s]["id"], "query": now[s]["query"],
                            "before": rank(base[s]), "after": rank(now[s])})
    notes.append(f"{mode} MRR {mrr(before):.4f} -> {mrr(after):.4f}; "
                 f"left top 3: {len(left_top3)}; entered top 3: {len(entered_top3)}")
    net_lost = len(left_top3) - len(entered_top3)
    if strict:
        moved = []
        for m in baseline["meta"].get("modes", MODES):
            moved += [now[s]["id"] for s in shared if rank(base[s], m) != rank(now[s], m)]
        if moved:
            failures.append(f"strict: {len(set(moved))} cases changed rank ({', '.join(sorted(set(moved))[:8])})")
    else:
        if drop > TOL_MRR:
            failures.append(f"{mode} MRR fell {drop:.4f} (tolerance {TOL_MRR})")
        if net_lost > TOL_HIT3 * len(shared):
            failures.append(f"{mode} net {net_lost} cases left the top 3 "
                            f"(tolerance {TOL_HIT3 * len(shared):.1f})")
    for s in shared:
        if "must" in now[s]["tags"] and not (rank(now[s]) and rank(now[s]) <= MUST_RANK):
            failures.append(f"must-pass case {now[s]['id']} is at rank {rank(now[s]) or '-'} "
                            f"(was {rank(base[s]) or '-'})")
    return failures, notes, changes


def cmd_check(args):
    if not os.path.exists(args.baseline):
        print(f"bench_golden: no baseline at {args.baseline}; run `run --save-baseline` first",
              file=sys.stderr)
        raise SystemExit(EXIT_ENV)
    with open(args.baseline, encoding="utf-8") as handle:
        baseline = json.load(handle)
    report, broken = run(args)
    out = args.out or os.path.join(
        GOLDEN_HOME, "runs", f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-check.json")
    save_report(report, out)
    failures, notes, changes = gate(baseline, report, strict=args.strict)
    same_corpus = baseline["meta"].get("corpus") == report["meta"]["corpus"]
    print(f"baseline {baseline['meta']['when']} ({baseline['meta']['embed_model']})  "
          f"corpus {'unchanged' if same_corpus else 'changed since baseline'}")
    for note in notes:
        print(note)
    for change in sorted(changes, key=lambda c: (c["after"] or 99) - (c["before"] or 99), reverse=True)[:20]:
        print(f"  {change['id']:18} {change['before'] or '-'!s:>3} -> {change['after'] or '-'!s:<3} {change['query'][:60]}")
    if broken:
        print(f"label health: {len(broken)} unusable cases (run `lint`)")
    if failures:
        print("\nFAIL")
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(EXIT_REGRESSION)
    if broken and not args.allow_stale:
        raise SystemExit(EXIT_LABELS)
    print("\nPASS")


# ---- compare: paired A/B ----------------------------------------------------
def sign_test(wins, losses):
    """Two-sided exact sign test over the cases that moved."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_ci(diffs, resamples=5000, seed=0):
    """95% interval for the mean per-case difference, by resampling cases."""
    if not diffs:
        return None, None
    rng, n = random.Random(seed), len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def paired(a, b, mode):
    rows_a = {r["sig"]: r for r in a["cases"] if r["status"] == "golden" and r["type"] != "no_answer"}
    rows_b = {r["sig"]: r for r in b["cases"] if r["status"] == "golden" and r["type"] != "no_answer"}
    shared = [s for s in rows_a if s in rows_b]
    rr = lambda row: (1.0 / row["ranks"][mode]["file"]) if row["ranks"][mode]["file"] else 0.0
    diffs = [rr(rows_b[s]) - rr(rows_a[s]) for s in shared]
    wins = [s for s, d in zip(shared, diffs) if d > 0]
    losses = [s for s, d in zip(shared, diffs) if d < 0]
    low, high = bootstrap_ci(diffs)
    hit = lambda rows, k: sum(1 for s in shared if rows[s]["ranks"][mode]["file"]
                              and rows[s]["ranks"][mode]["file"] <= k)
    return {"n": len(shared), "wins": len(wins), "losses": len(losses),
            "ties": len(shared) - len(wins) - len(losses),
            "mrr_a": round(sum(rr(rows_a[s]) for s in shared) / len(shared), 4) if shared else None,
            "mrr_b": round(sum(rr(rows_b[s]) for s in shared) / len(shared), 4) if shared else None,
            "delta_mrr": round(sum(diffs) / len(diffs), 4) if diffs else None,
            "ci95": [round(low, 4), round(high, 4)] if diffs else None,
            "p_sign": round(sign_test(len(wins), len(losses)), 4),
            "hit@1": [hit(rows_a, 1), hit(rows_b, 1)], "hit@3": [hit(rows_a, 3), hit(rows_b, 3)],
            "flips": [{"id": rows_b[s]["id"], "query": rows_b[s]["query"],
                       "a": rows_a[s]["ranks"][mode]["file"], "b": rows_b[s]["ranks"][mode]["file"]}
                      for s in wins + losses]}


def cmd_compare(args):
    with open(args.a, encoding="utf-8") as handle:
        a = json.load(handle)
    with open(args.b, encoding="utf-8") as handle:
        b = json.load(handle)
    same_corpus = a["meta"]["corpus"] == b["meta"]["corpus"]
    print(f"A: {a['meta']['embed_model']}  ({a['meta']['tag']}, {a['meta']['when']})")
    print(f"B: {b['meta']['embed_model']}  ({b['meta']['tag']}, {b['meta']['when']})")
    print(f"corpus: {'identical text' if same_corpus else 'DIFFERENT text: not a like-for-like comparison'}")
    modes = [m for m in a["meta"]["modes"] if m in b["meta"]["modes"]]
    results = {m: paired(a, b, m) for m in modes}
    print(f"\n{'mode':8} {'n':>4} {'MRR A':>7} {'MRR B':>7} {'delta':>8} {'95% CI':>18} "
          f"{'B wins':>6} {'B loses':>7} {'p':>6} {'hit@1':>9} {'hit@3':>9}")
    for mode, r in results.items():
        ci = f"[{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]" if r["ci95"] else "-"
        print(f"{mode:8} {r['n']:>4} {r['mrr_a']:>7} {r['mrr_b']:>7} {r['delta_mrr']:>+8.4f} {ci:>18} "
              f"{r['wins']:>6} {r['losses']:>7} {r['p_sign']:>6} "
              f"{str(r['hit@1'][0]) + '>' + str(r['hit@1'][1]):>9} {str(r['hit@3'][0]) + '>' + str(r['hit@3'][1]):>9}")
    for name, report in (("A", a), ("B", b)):
        s = report["abstention"]["sim"]
        print(f"no-answer AUROC {name}: {s['auroc']} (false alarms at 95% recall {s['fpr_at_tpr95']})  "
              f"embed p50 {report['latency_ms']['embed']['p50']} ms")
    shown = results.get(args.mode) or next(iter(results.values()))
    print(f"\ncases that moved ({args.mode}):")
    for flip in sorted(shown["flips"], key=lambda f: (1.0 / f["b"] if f["b"] else 0) - (1.0 / f["a"] if f["a"] else 0))[:args.show]:
        print(f"  {flip['id']:18} A {flip['a'] or '-'!s:>3}  B {flip['b'] or '-'!s:>3}  {flip['query'][:60]}")
    if args.json:
        print(json.dumps(results, indent=1))
    if args.gate:
        reasons = [] if same_corpus else ["the two runs are over different text"]
        for mode in BAKEOFF_MODES:
            r = results.get(mode)
            if not r or not r["n"]:
                reasons.append(f"{mode}: not present in both runs")
            elif r["delta_mrr"] < MIN_GAIN:
                reasons.append(f"{mode}: MRR gain {r['delta_mrr']:+.4f} is under {MIN_GAIN}")
            elif r["wins"] <= r["losses"]:
                reasons.append(f"{mode}: {r['wins']} wins against {r['losses']} losses")
        print(f"\nbake-off gate (B must gain >= {MIN_GAIN} MRR with more wins than losses on "
              f"{' and '.join(BAKEOFF_MODES)}, same text): {'PASS' if not reasons else 'FAIL'}")
        for reason in reasons:
            print(f"  {reason}")
        if reasons:
            raise SystemExit(EXIT_REGRESSION)


# ---- lint / freeze / reembed ------------------------------------------------
def cmd_lint(args):
    path = cases_path(args.cases)
    try:
        cases = load_cases(path)
        index = Index(load_engine(args.db))
    except (OSError, ValueError) as error:
        print(f"bench_golden: {error}", file=sys.stderr)
        raise SystemExit(EXIT_LABELS)
    problems = lint_cases(cases, index.files, list(index.chunks.values()))
    counts = {}
    for case in cases:
        counts[case["status"]] = counts.get(case["status"], 0) + 1
    print(f"{path}: {len(cases)} cases ({', '.join(f'{v} {k}' for k, v in sorted(counts.items()))})")
    for problem in problems:
        print(f"  {problem['level']:5} {problem['id']:18} {problem['code']:20} {problem['detail']}")
    errors = sum(1 for p in problems if p["level"] == "error")
    print(f"{errors} errors, {len(problems) - errors} warnings")
    if errors:
        raise SystemExit(EXIT_LABELS)


def cmd_freeze(args):
    """Copy the live DB to an immutable snapshot named by date and content hash.
    The source is hashed before and after the copy: a publisher replacing the
    file mid-copy would otherwise freeze a torn database."""
    source = args.db or load_engine().DB_PATH
    before = file_sha(source)
    os.makedirs(args.to, exist_ok=True)
    target = os.path.join(args.to, f"{datetime.now().strftime('%Y%m%d')}-{before[:8]}.db")
    if os.path.exists(target):
        print(target)
        return
    partial = target + ".partial"
    shutil.copyfile(source, partial)
    if file_sha(partial) != before or file_sha(source) != before:
        os.remove(partial)
        print("bench_golden: the database changed during the copy; run freeze again", file=sys.stderr)
        raise SystemExit(EXIT_ENV)
    os.chmod(partial, 0o444)
    os.replace(partial, target)
    print(target)


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def cmd_reembed(args):
    """Build the B side of an embedder bake-off: same chunks, new vectors, in a
    copy. --parity N instead re-embeds N chunks with the configured model and
    compares them to the stored vectors, which proves this code path produces
    what the indexer produced before it is trusted with a different model."""
    import libsql
    engine = load_engine(args.db, args.embed_url, args.embed_model)
    if args.parity:
        con = libsql.connect(f"file:{args.db}?mode=ro", _uri=True)
        cur = con.cursor()
        total = cur.execute("SELECT count(*) FROM chunks").fetchall()[0][0]
        step = max(1, total // args.parity)
        rows = cur.execute("SELECT id, txt, vector_extract(emb) FROM chunks WHERE id % ? = 0 LIMIT ?",
                           (step, args.parity)).fetchall()
        sims = [cosine(engine.embed(txt, is_query=False), json.loads(stored)) for _, txt, stored in rows]
        print(f"parity over {len(sims)} chunks with {engine.MODEL}: "
              f"min cosine {min(sims):.5f}, mean {sum(sims) / len(sims):.5f}")
        if min(sims) < 0.99:
            print("bench_golden: stored vectors do not match this model/prompt path", file=sys.stderr)
            raise SystemExit(EXIT_REGRESSION)
        return
    if not args.out or not args.embed_model:
        print("bench_golden: reembed needs --out and --embed-model", file=sys.stderr)
        raise SystemExit(EXIT_ENV)
    if os.path.exists(args.out):
        print(f"bench_golden: {args.out} already exists; refusing to overwrite", file=sys.stderr)
        raise SystemExit(EXIT_ENV)
    probe = engine.embed("dimension probe", is_query=False)
    if len(probe) != engine.DIM:
        print(f"bench_golden: {args.embed_model} returns {len(probe)} dimensions; "
              f"the index column holds {engine.DIM}", file=sys.stderr)
        raise SystemExit(EXIT_ENV)
    shutil.copyfile(args.db, args.out)
    os.chmod(args.out, 0o644)
    con = libsql.connect(args.out)
    cur = con.cursor()
    rows = cur.execute("SELECT id, txt FROM chunks ORDER BY id").fetchall()
    started = time.perf_counter()
    for done, (cid, txt) in enumerate(rows, 1):
        cur.execute("UPDATE chunks SET emb = vector32(?) WHERE id = ?",
                    (str(engine.embed(txt, is_query=False)), cid))
        if done % 200 == 0:
            con.commit()
            print(f"  {done}/{len(rows)}", file=sys.stderr)
    cur.execute("CREATE TABLE IF NOT EXISTS bench_meta(key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT OR REPLACE INTO bench_meta VALUES('embed_model', ?)", (args.embed_model,))
    con.commit()
    elapsed = time.perf_counter() - started
    print(f"re-embedded {len(rows)} chunks with {args.embed_model} in {elapsed:.0f}s "
          f"({len(rows) / elapsed:.1f} chunks/s) -> {args.out}")


# ---- cli --------------------------------------------------------------------
def _cli(argv=None):
    ap = argparse.ArgumentParser(description="Golden retrieval tests for recall.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--cases", help="case file (JSON Lines)")
        p.add_argument("--db", help="database to score; default is the configured one")

    def running(p):
        common(p)
        p.add_argument("--modes", default=",".join(MODES))
        p.add_argument("--pool", type=int, default=POOL)
        p.add_argument("--k", type=int, default=5, help="top results kept per case in the report")
        p.add_argument("--embed-url")
        p.add_argument("--embed-model")
        p.add_argument("--tag", default="run")
        p.add_argument("--out", help="where to write the JSON report")
        p.add_argument("--baseline", default=BASELINE)
        p.add_argument("--allow-stale", action="store_true",
                       help="exit 0 even when some labels are unusable")
        p.add_argument("-v", "--verbose", action="store_true")

    p = sub.add_parser("run", help="score the cases")
    running(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--save-baseline", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("check", help="run, then gate against the baseline")
    running(p)
    p.add_argument("--strict", action="store_true",
                   help="fail on any rank change in any mode (frozen-snapshot parity)")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("compare", help="paired comparison of two saved runs")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--mode", default=GATE_MODE)
    p.add_argument("--show", type=int, default=20)
    p.add_argument("--gate", action="store_true", help="apply the bake-off adoption rule")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("lint", help="check labels against the index")
    common(p)
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("freeze", help="copy the database to an immutable snapshot")
    p.add_argument("--db")
    p.add_argument("--to", default=os.path.join(GOLDEN_HOME, "snapshots"))
    p.set_defaults(fn=cmd_freeze)

    p = sub.add_parser("reembed", help="re-embed a snapshot copy with another model")
    p.add_argument("--db", required=True)
    p.add_argument("--out")
    p.add_argument("--embed-model")
    p.add_argument("--embed-url")
    p.add_argument("--parity", type=int, default=0, metavar="N",
                   help="no writes: re-embed N chunks and compare with the stored vectors")
    p.set_defaults(fn=cmd_reembed)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    _cli()
