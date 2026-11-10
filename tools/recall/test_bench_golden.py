"""Tests for bench_golden.py.

The scoring, label-health, and gate logic is pure and tested directly. The
end-to-end class drives the real CLI through subprocess against a throwaway
`$HOME`, a synthetic corpus indexed by the real engine, and a loopback embedding
server. Nothing here reads `~/.recall` or a private case file.
"""
import hashlib
import json
import os
import site
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "recall.py"
BENCH = HERE / "bench_golden.py"
DIM = 768
_STOP = {"task", "search", "result", "query", "title", "none", "text"}

sys.path.insert(0, str(HERE))
import bench_golden as bg  # noqa: E402

try:
    import libsql  # noqa: F401
    HAVE_LIBSQL = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_LIBSQL = False


def chunk(cite, txt="", line=1, cid=0):
    return {"id": cid, "cite": cite, "path": "/abs/" + cite, "line": line, "txt": bg.norm(txt)}


def case(cid="c1", query="q", expect=None, avoid=None, **extra):
    base = {"id": cid, "query": query, "type": "known_item", "origin": "authored",
            "status": "golden", "tags": [], "expect": expect or [], "avoid": avoid or [], "_line": 1}
    base.update(extra)
    return base


def row(cid, rank, mode_ranks=None, tags=(), ctype="known_item", status="golden", sig=None,
        sim=0.5, rrf=0.03):
    ranks = mode_ranks or {m: rank for m in bg.MODES}
    return {"id": cid, "sig": sig or cid, "query": f"query {cid}", "type": ctype,
            "origin": "authored", "status": status, "tags": list(tags), "has_passage": False,
            "has_avoid": False, "sim": sim, "rrf": rrf,
            "ms": {"embed": 1.0, "vector": 1.0, "fts": 1.0},
            "ranks": {m: {"file": r, "passage": None, "avoid": None, "ndcg": None}
                      for m, r in ranks.items()},
            "top": {m: [] for m in ranks}}


def report(rows):
    return {"meta": {"modes": list(bg.MODES), "corpus": "x", "embed_model": "m", "when": "t",
                     "tag": "t"},
            "cases": rows, "abstention": bg.abstention(rows),
            "latency_ms": {"embed": {"p50": 1.0, "p95": 1.0}}}


class LoadCasesTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_defaults_comments_and_blank_lines(self):
        path = self.write('# header\n\n{"id": "a", "query": "find it", "expect": [{"path": "x.md"}]}\n')
        (loaded,) = bg.load_cases(path)
        self.assertEqual((loaded["status"], loaded["type"], loaded["origin"]),
                         ("golden", "known_item", "authored"))
        self.assertEqual((loaded["avoid"], loaded["tags"], loaded["_line"]), ([], [], 3))

    def test_shape_errors_name_the_line(self):
        for text, needle in (('{"id": "a", "query": "q"}\n{not json}\n', ":2: not valid JSON"),
                             ('{"query": "q"}\n', ":1: missing 'id'"),
                             ('{"id": "a", "query": " "}\n', ":1: missing 'query'"),
                             ('{"id": "a", "query": "q", "expect": ["x.md"]}\n', ":1: 'expect'"),
                             ('[1]\n', ":1: a case must be a JSON object")):
            with self.assertRaises(ValueError) as raised:
                bg.load_cases(self.write(text))
            self.assertIn(needle, str(raised.exception))

    def test_signature_tracks_labels_not_bookkeeping(self):
        one = case(expect=[{"path": "a.md"}])
        same = case(cid="renamed", expect=[{"path": "a.md"}], tags=["must"], status="candidate")
        relabeled = case(expect=[{"path": "b.md"}])
        self.assertEqual(bg.signature(one), bg.signature(same))
        self.assertNotEqual(bg.signature(one), bg.signature(relabeled))

    def test_example_file_is_loadable(self):
        loaded = bg.load_cases(str(HERE / "golden_cases.example.jsonl"))
        self.assertGreaterEqual(len(loaded), 5)
        self.assertEqual(bg.lint_cases(loaded, ["notes/deploy_runbook.md"], [])[0]["code"], "stale_passage")


class ScoringTests(unittest.TestCase):
    def test_first_rank_by_path_and_passage(self):
        ranked = [chunk("notes/other.md", "nothing"),
                  chunk("notes/plan.md", "the intro section"),
                  chunk("notes/plan.md", "Rollout:   kubectl ROLLOUT status")]
        target = [{"path": "plan.md", "passage": "kubectl rollout"}]
        self.assertEqual(bg.first_rank(ranked, target), 2)
        self.assertEqual(bg.first_rank(ranked, target, need_passage=True), 3)
        self.assertIsNone(bg.first_rank(ranked, [{"path": "missing.md"}]))
        # a target without a passage cannot satisfy a passage-level match
        self.assertIsNone(bg.first_rank(ranked, [{"path": "plan.md"}], need_passage=True))

    def test_path_matches_citation_or_absolute_path(self):
        self.assertTrue(bg.path_matches("/abs/notes/a.md", chunk("notes/a.md")))
        self.assertTrue(bg.path_matches("notes/a", chunk("notes/a.md")))
        self.assertFalse(bg.path_matches("notes/b", chunk("notes/a.md")))

    def test_ndcg_grades_and_counts_a_file_once(self):
        targets = [{"path": "best.md", "grade": 2}, {"path": "ok.md", "grade": 1}]
        ideal = [chunk("best.md"), chunk("ok.md")]
        self.assertAlmostEqual(bg.ndcg(ideal, targets), 1.0)
        swapped = [chunk("ok.md"), chunk("best.md")]
        self.assertLess(bg.ndcg(swapped, targets), 1.0)
        repeated = [chunk("best.md"), chunk("best.md"), chunk("best.md")]
        self.assertAlmostEqual(bg.ndcg(repeated, targets), bg.ndcg([chunk("best.md")], targets))
        self.assertEqual(bg.ndcg([chunk("x.md")], targets), 0.0)
        self.assertIsNone(bg.ndcg(ideal, []))

    def test_fuse_matches_the_engine_formula_and_tie_order(self):
        order, scores = bg.fuse([1, 2, 3], [3, 4], 60)
        self.assertEqual(order[0], 3)                    # in both arms
        self.assertAlmostEqual(scores[3], 1 / 62 + 1 / 60)
        self.assertEqual(order[1:], [1, 2, 4])           # 1 before 4 on a tie; 2 outranks 4
        self.assertEqual(bg.fuse([], [], 60), ([], {}))
        self.assertEqual(bg.fuse([], [7, 8], 60)[0], [7, 8])

    def test_score_case_reports_avoid_and_passage(self):
        ranked = [chunk("old/policy_2023.md"), chunk("policy.md", "rotate every 90 days")]
        scored = bg.score_case(case(expect=[{"path": "policy.md", "passage": "90 days"}],
                                    avoid=[{"path": "policy_2023"}]), ranked)
        self.assertEqual((scored["file"], scored["passage"], scored["avoid"]), (2, 2, 1))
        empty = bg.score_case(case(type="no_answer"), ranked)
        self.assertEqual((empty["file"], empty["passage"], empty["avoid"], empty["ndcg"]),
                         (None, None, None, None))

    def test_summarize_counts_and_avoid_above_expected(self):
        rows = [row("a", 1), row("b", 4), row("c", None), row("n", None, ctype="no_answer")]
        rows[1]["has_avoid"] = True
        rows[1]["ranks"]["hybrid"]["avoid"] = 2          # outranks the expected target
        rows[2]["has_avoid"] = True
        rows[2]["ranks"]["hybrid"]["avoid"] = 9          # expected never retrieved
        rows[0]["has_avoid"] = True
        rows[0]["ranks"]["hybrid"]["avoid"] = 5          # below the expected target: fine
        summary = bg.summarize(rows, "hybrid")
        self.assertEqual((summary["n"], summary["hit@1"], summary["hit@3"], summary["hit@5"]),
                         (3, 1, 1, 2))
        self.assertAlmostEqual(summary["mrr"], round((1 + 0.25) / 3, 4))
        self.assertEqual(summary["avoid"], {"n": 3, "above_expected": 2, "at_rank_1": 0})

    def test_breakdown_groups_by_type_and_by_tag(self):
        rows = [row("a", 1, tags=["x", "y"]), row("b", None, tags=["x"], ctype="paraphrase")]
        self.assertEqual(bg.breakdown(rows, "hybrid", "type")["paraphrase"]["hit@1"], 0)
        self.assertEqual(bg.breakdown(rows, "hybrid", "tags")["x"]["n"], 2)

    def test_auroc_and_false_alarm_rate(self):
        self.assertEqual(bg.auroc([0.9, 0.8], [0.1, 0.2]), 1.0)
        self.assertEqual(bg.auroc([0.1], [0.9]), 0.0)
        self.assertEqual(bg.auroc([0.5], [0.5]), 0.5)
        self.assertIsNone(bg.auroc([], [0.5]))
        positives = [i / 100 for i in range(1, 101)]
        rate, threshold = bg.fpr_at_tpr(positives, [0.01, 0.5, 0.99, 0.02])
        self.assertAlmostEqual(threshold, 0.06)
        self.assertEqual(rate, 0.5)
        self.assertEqual(bg.fpr_at_tpr([], [0.1]), (None, None))

    def test_abstention_separates_answerable_from_no_answer(self):
        rows = [row("a", 1, sim=0.8), row("b", 1, sim=0.7),
                row("n", None, ctype="no_answer", sim=0.3)]
        self.assertEqual(bg.abstention(rows)["sim"]["auroc"], 1.0)


class LintTests(unittest.TestCase):
    FILES = ["notes/a.md", "notes/sub/a.md", "notes/b.md"]
    CHUNKS = [chunk("notes/b.md", "The rollout uses a canary first")]

    def codes(self, cases):
        return sorted((p["id"], p["level"], p["code"]) for p in bg.lint_cases(cases, self.FILES, self.CHUNKS))

    def test_clean_case_has_no_problems(self):
        self.assertEqual(self.codes([case(expect=[{"path": "notes/b.md", "passage": "canary  FIRST"}])]), [])

    def test_errors(self):
        found = self.codes([
            case("stale", query="one", expect=[{"path": "gone.md"}]),
            case("passage", query="two", expect=[{"path": "notes/b.md", "passage": "blue green"}]),
            case("empty", query="three"),
            case("noans", query="four", type="no_answer", expect=[{"path": "notes/b.md"}]),
            case("dup", query="five", expect=[{"path": "notes/b.md"}]),
            case("dup", query="six", expect=[{"path": "notes/b.md"}]),
            case("status", query="seven", status="draft", expect=[{"path": "notes/b.md"}]),
        ])
        self.assertEqual(found, [("dup", "error", "duplicate_id"), ("empty", "error", "empty_expect"),
                                 ("noans", "error", "no_answer_has_expect"),
                                 ("passage", "error", "stale_passage"),
                                 ("stale", "error", "stale_path"), ("status", "error", "bad_status")])

    def test_warnings_do_not_make_a_case_unusable(self):
        cases = [case("amb", query="one", expect=[{"path": "a.md"}]),
                 case("twin", query="ONE ", expect=[{"path": "notes/b.md"}]),
                 case("avoid", query="two", expect=[{"path": "notes/b.md"}], avoid=[{"path": "gone"}]),
                 case("odd", query="three", type="vibes", expect=[{"path": "notes/b.md"}])]
        problems = bg.lint_cases(cases, self.FILES, self.CHUNKS)
        self.assertEqual(sorted(p["code"] for p in problems),
                         ["ambiguous_path", "duplicate_query", "stale_avoid", "unknown_type"])
        self.assertEqual(bg.unusable(problems), set())

    def test_retired_and_review_cases_are_not_checked_against_the_index(self):
        cases = [case("old", status="retired", expect=[{"path": "gone.md"}]),
                 case("ask", query="other", status="review", expect=[{"path": "gone.md"}])]
        self.assertEqual(self.codes(cases), [])


class GateTests(unittest.TestCase):
    def base(self):
        return [row(f"c{i}", 1) for i in range(40)] + [row("n", None, ctype="no_answer")]

    def test_identical_runs_pass(self):
        failures, notes, changes = bg.gate(report(self.base()), report(self.base()))
        self.assertEqual((failures, changes), ([], []))
        self.assertIn("40 cases compared", notes[0])

    def test_small_drift_is_tolerated_and_reported(self):
        current = self.base()
        current[0] = row("c0", 2)
        failures, _, changes = bg.gate(report(self.base()), report(current))
        self.assertEqual(failures, [])
        self.assertEqual(changes, [{"id": "c0", "query": "query c0", "before": 1, "after": 2}])

    def test_mrr_drop_beyond_tolerance_fails(self):
        current = self.base()
        for i in range(4):
            current[i] = row(f"c{i}", 3)        # still top 3, but MRR falls 4 * (2/3) / 40
        failures, _, _ = bg.gate(report(self.base()), report(current))
        self.assertEqual(len(failures), 1)
        self.assertIn("MRR fell", failures[0])

    def test_cases_leaving_the_top_three_fail(self):
        baseline = [row(f"c{i}", 3) for i in range(40)]
        current = [row(f"c{i}", 4 if i < 3 else 3) for i in range(40)]
        failures, _, _ = bg.gate(report(baseline), report(current))
        self.assertTrue(any("left the top 3" in f for f in failures), failures)
        self.assertFalse(any("MRR fell" in f for f in failures), failures)

    def test_gains_offset_losses_in_the_top_three_count(self):
        baseline = [row(f"c{i}", 3) for i in range(37)] + [row(f"c{i}", 4) for i in range(37, 40)]
        current = [row(f"c{i}", 4 if i < 3 else 3) for i in range(40)]
        failures, _, _ = bg.gate(report(baseline), report(current))
        self.assertEqual(failures, [])

    def test_must_case_outside_the_top_three_fails_even_within_tolerance(self):
        # 1 of 100 slipping from rank 1 to 4 is inside both tolerances
        baseline = [row(f"c{i}", 1, tags=["must"] if i == 0 else ()) for i in range(100)]
        current = [row(f"c{i}", 4 if i == 0 else 1, tags=["must"] if i == 0 else ()) for i in range(100)]
        failures, _, _ = bg.gate(report(baseline), report(current))
        self.assertEqual(failures, ["must-pass case c0 is at rank 4 (was 1)"])
        current[0] = row("c0", 4)                          # same slip, not must-pass
        self.assertEqual(bg.gate(report(baseline), report(current))[0], [])

    def test_relabeled_new_and_removed_cases_are_left_out(self):
        current = self.base()[1:]
        current.append(row("fresh", None))                 # new and missing: not a regression
        current[0] = row("c1", None, sig="relabeled")      # label changed since the baseline
        failures, notes, _ = bg.gate(report(self.base()), report(current))
        self.assertEqual(failures, [])
        self.assertIn("38 cases compared; 2 new or relabeled; 2 gone", notes[0])

    def test_candidates_are_never_gated(self):
        baseline = self.base() + [row("cand", 1, status="candidate")]
        current = self.base() + [row("cand", None, status="candidate", tags=["must"])]
        self.assertEqual(bg.gate(report(baseline), report(current))[0], [])

    def test_strict_fails_on_any_move_in_any_mode(self):
        current = self.base()
        current[5] = row("c5", 1, mode_ranks={"hybrid": 1, "vector": 2, "fts": 1})
        self.assertEqual(bg.gate(report(self.base()), report(current))[0], [])
        failures, _, _ = bg.gate(report(self.base()), report(current), strict=True)
        self.assertEqual(failures, ["strict: 1 cases changed rank (c5)"])

    def test_nothing_in_common_is_a_failure_not_a_pass(self):
        failures, _, _ = bg.gate(report([row("a", 1)]), report([row("b", 1)]))
        self.assertIn("no comparable cases", failures[0])


class CompareTests(unittest.TestCase):
    def test_sign_test(self):
        self.assertEqual(bg.sign_test(0, 0), 1.0)
        self.assertEqual(bg.sign_test(5, 5), 1.0)
        self.assertAlmostEqual(bg.sign_test(10, 0), 2 / 1024)
        self.assertAlmostEqual(bg.sign_test(0, 10), 2 / 1024)

    def test_bootstrap_is_seeded_and_brackets_the_mean(self):
        diffs = [0.5] * 30 + [0.0] * 30 + [-0.25] * 10
        first, second = bg.bootstrap_ci(diffs), bg.bootstrap_ci(diffs)
        self.assertEqual(first, second)
        mean = sum(diffs) / len(diffs)
        self.assertLess(first[0], mean)
        self.assertGreater(first[1], mean)
        self.assertEqual(bg.bootstrap_ci([]), (None, None))
        self.assertEqual(bg.bootstrap_ci([0.0] * 20), (0.0, 0.0))

    def test_paired_counts_wins_losses_and_flips(self):
        a = report([row("a", 3), row("b", 1), row("c", None), row("d", 2)])
        b = report([row("a", 1), row("b", 2), row("c", None), row("d", 2)])
        result = bg.paired(a, b, "hybrid")
        self.assertEqual((result["n"], result["wins"], result["losses"], result["ties"]), (4, 1, 1, 2))
        self.assertEqual(result["hit@1"], [1, 1])
        self.assertAlmostEqual(result["delta_mrr"], round(((1 - 1 / 3) + (0.5 - 1)) / 4, 4))
        self.assertEqual(sorted(f["id"] for f in result["flips"]), ["a", "b"])


# ---- end to end -------------------------------------------------------------
def _vector(text):
    vec = [0.0] * DIM
    for raw in text.lower().split():
        tok = "".join(c for c in raw if c.isalnum())
        if len(tok) <= 2 or tok in _STOP:
            continue
        vec[int(hashlib.sha1(tok.encode()).hexdigest(), 16) % DIM] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


class _EmbedHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.server.models.append(payload.get("model"))
        if self.server.fail:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"forced failure")
            return
        vec = _vector(payload.get("input", ""))
        if payload.get("model") == "other-model":
            vec = vec[1:] + vec[:1]          # a different embedding space
        body = json.dumps({"data": [{"embedding": vec}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


NOTES = {
    "ops/deploy_runbook.md": "# Deploy\n\nShip to staging with the quantumsprocket rollout command.\n",
    "ops/deploy_runbook_2023.md": "# Deploy (old)\n\nThe retired staging procedure used flangewidget scripts.\n",
    "finance/billing.md": "# Billing\n\nInvoices are stored in the ledgerfox database cluster.\n",
    "people/onboarding.md": "# Onboarding\n\nNew engineers request a zephyrbadge on day one.\n",
}
CASES = [
    {"id": "deploy", "query": "quantumsprocket rollout staging", "tags": ["must"],
     "expect": [{"path": "ops/deploy_runbook.md", "passage": "quantumsprocket rollout"}],
     "avoid": [{"path": "deploy_runbook_2023", "why": "superseded"}]},
    {"id": "billing", "query": "ledgerfox database invoices", "expect": [{"path": "finance/billing.md"}]},
    {"id": "onboard", "query": "zephyrbadge engineers", "type": "keyword",
     "expect": [{"path": "people/onboarding.md"}]},
    {"id": "none", "query": "tungsten boiling point", "type": "no_answer", "expect": []},
    {"id": "later", "query": "zephyrbadge", "status": "candidate", "expect": [{"path": "onboarding"}]},
]


@unittest.skipUnless(HAVE_LIBSQL, "libsql driver not installed")
class GoldenEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.corpus = self.home / "notes"
        for rel, text in NOTES.items():
            (self.corpus / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.corpus / rel).write_text(text, encoding="utf-8")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _EmbedHandler)
        self.server.fail = False
        self.server.models = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.db = self.home / ".recall" / "memory.db"
        (self.home / ".recall").mkdir()
        (self.home / ".recall" / "config.json").write_text(json.dumps({
            "sources": [{"label": "notes", "path": str(self.corpus)}],
            "db_path": str(self.db), "read_only": False,
            "inbox": str(self.corpus / "_inbox"), "retrieval_mode": "hybrid",
            "embed_url": f"http://127.0.0.1:{self.server.server_address[1]}/v1/embeddings",
            "embed_model": "test-model"}), encoding="utf-8")
        self.cases = self.home / ".recall" / "golden" / "cases.jsonl"
        self.cases.parent.mkdir()
        self.write_cases(CASES)
        self.cli(ENGINE, "index")

    def write_cases(self, cases):
        self.cases.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")

    def cli(self, script, *args, code=0):
        env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "PATH": os.environ.get("PATH", ""),
               # HOME is a temp dir; keep `pip install --user` packages importable.
               "PYTHONUSERBASE": site.getuserbase()}
        proc = subprocess.run([sys.executable, str(script), *args],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, code, msg=f"{args}:\n{proc.stdout}\n{proc.stderr}")
        return proc

    def golden(self, *args, code=0):
        return self.cli(BENCH, *args, code=code)

    def test_run_scores_the_private_case_file_like_the_real_cli(self):
        out = self.home / "run.json"
        self.golden("run", "--out", str(out), "--json")
        result = json.loads(out.read_text())
        self.assertEqual(result["meta"]["n_scored"], 5)
        self.assertEqual(result["meta"]["cases_file"], str(self.cases))
        hybrid = result["summary"]["hybrid"]
        self.assertEqual((hybrid["n"], hybrid["hit@1"], hybrid["mrr"]), (3, 3, 1.0))
        self.assertEqual(hybrid["passage"], {"n": 1, "hit@1": 1, "hit@3": 1, "hit@5": 1, "mrr": 1.0})
        self.assertEqual(hybrid["avoid"]["above_expected"], 0)
        self.assertEqual(result["candidates"]["hybrid"]["n"], 1)
        self.assertEqual(result["abstention"]["sim"]["no_answer"], 1)
        self.assertEqual(result["abstention"]["sim"]["auroc"], 1.0)
        by_id = {r["id"]: r for r in result["cases"]}
        # the report's top hits are the engine's own answer, citation and line
        shown = self.cli(ENGINE, "quantumsprocket rollout staging").stdout
        cited = [line.split("] ", 1)[1] for line in shown.splitlines() if line.startswith("[")]
        self.assertEqual(by_id["deploy"]["top"]["hybrid"], cited)
        self.assertEqual(by_id["none"]["ranks"]["hybrid"]["file"], None)

    def test_check_passes_unchanged_and_fails_when_retrieval_breaks(self):
        self.golden("run", "--save-baseline")
        self.assertTrue((self.cases.parent / "baseline.json").exists())
        self.assertIn("PASS", self.golden("check").stdout)
        self.assertIn("PASS", self.golden("check", "--strict").stdout)
        # near-duplicate notes crowd the right one out of the top results: the
        # label is still valid, retrieval got worse, and the gate must say so
        for n in range(5):
            (self.corpus / "ops" / f"copy{n}.md").write_text(
                f"# Copy {n}\n\nquantumsprocket rollout staging\n", encoding="utf-8")
        self.cli(ENGINE, "index")
        failed = self.golden("check", code=bg.EXIT_REGRESSION)
        self.assertIn("FAIL", failed.stdout)
        self.assertIn("must-pass case deploy", failed.stdout)
        self.assertIn("corpus changed since baseline", failed.stdout)

    def test_a_label_that_went_stale_is_reported_as_a_label_problem(self):
        self.golden("run", "--save-baseline")
        (self.corpus / "ops" / "deploy_runbook.md").write_text(
            "# Deploy\n\nMoved. See the wiki.\n", encoding="utf-8")
        self.cli(ENGINE, "index")
        stale = self.golden("check", code=bg.EXIT_LABELS)
        self.assertIn("label health: 1 unusable cases", stale.stdout)
        self.assertNotIn("PASS", stale.stdout)

    def test_check_without_a_baseline_is_an_environment_error(self):
        self.assertIn("no baseline", self.golden("check", code=bg.EXIT_ENV).stderr)

    def test_stale_labels_block_the_run_and_the_baseline(self):
        self.write_cases(CASES + [{"id": "stale", "query": "anything", "expect": [{"path": "gone.md"}]}])
        self.assertIn("stale_path", self.golden("lint", code=bg.EXIT_LABELS).stdout)
        self.golden("run", code=bg.EXIT_LABELS)
        refused = self.golden("run", "--save-baseline", "--allow-stale", code=bg.EXIT_LABELS)
        self.assertIn("refusing to save a baseline", refused.stderr)
        self.assertFalse((self.cases.parent / "baseline.json").exists())
        self.golden("run", "--allow-stale")

    def test_embedder_down_fails_closed_instead_of_scoring_keyword_only(self):
        self.server.fail = True
        failed = self.golden("run", code=bg.EXIT_ENV)
        self.assertIn("embedder unavailable", failed.stderr)
        self.assertEqual(list((self.home / ".recall" / "golden").glob("runs/*.json")), [])
        # keyword-only is still measurable when asked for explicitly
        self.golden("run", "--modes", "fts")

    def test_freeze_writes_a_read_only_copy_the_run_can_score(self):
        frozen = Path(self.golden("freeze").stdout.strip())
        self.assertEqual(frozen.parent, self.home / ".recall" / "golden" / "snapshots")
        self.assertEqual(frozen.read_bytes(), self.db.read_bytes())
        self.assertEqual(frozen.stat().st_mode & 0o222, 0)
        self.assertEqual(self.golden("freeze").stdout.strip(), str(frozen))   # idempotent
        before = frozen.read_bytes()
        self.golden("run", "--db", str(frozen), "--save-baseline")
        self.assertIn("corpus unchanged", self.golden("check", "--db", str(frozen), "--strict").stdout)
        self.assertEqual(frozen.read_bytes(), before)

    def test_reembed_builds_a_comparable_copy_and_refuses_a_model_mismatch(self):
        frozen = self.golden("freeze").stdout.strip()
        self.assertIn("min cosine 1.0", self.golden("reembed", "--db", frozen, "--parity", "3").stdout)
        other = str(self.home / "other.db")
        self.golden("reembed", "--db", frozen, "--out", other, "--embed-model", "other-model")
        self.golden("reembed", "--db", frozen, "--out", other, "--embed-model", "other-model",
                    code=bg.EXIT_ENV)                                        # never overwrites
        a, b = str(self.home / "a.json"), str(self.home / "b.json")
        self.golden("run", "--db", frozen, "--out", a, "--tag", "a")
        self.server.models.clear()
        self.golden("run", "--db", other, "--out", b, "--tag", "b")
        # queries against the copy use the model that built it, with no flag
        self.assertEqual(set(self.server.models), {"other-model"})
        self.assertEqual(json.loads(Path(b).read_text())["meta"]["embed_model"], "other-model")
        mismatch = self.golden("run", "--db", other, "--embed-model", "test-model", code=bg.EXIT_ENV)
        self.assertIn("was embedded with other-model", mismatch.stderr)
        compared = self.golden("compare", a, b, "--gate", code=bg.EXIT_REGRESSION).stdout
        self.assertIn("corpus: identical text", compared)
        self.assertIn("bake-off gate", compared)
        self.assertIn("FAIL", compared)


if __name__ == "__main__":
    unittest.main()
