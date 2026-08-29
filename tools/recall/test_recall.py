import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
import uuid
from unittest import mock

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "recall.py"
LAUNCHER = HERE / "launcher.py"


def load_engine(home: Path, config: dict | None = None, env: dict | None = None):
    recall_home = home / ".recall"
    recall_home.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (recall_home / "config.json").write_text(json.dumps(config), encoding="utf-8")
    name = f"recall_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, ENGINE)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {"HOME": str(home), **(env or {})}, clear=True):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class RecallConfigTests(unittest.TestCase):
    def test_config_loads_role_paths_and_retrieval_mode(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            module = load_engine(home, {
                "sources": [{"label": "notes", "path": "~/notes"}],
                "db_path": "~/.recall/shared.db",
                "publish_path": "~/sync/published.db",
                "read_only": True,
                "inbox": "~/notes/_inbox",
                "retrieval_mode": "hybrid",
                "exclude_files": ["MEMORY.md"],
                "embed_url": "http://localhost:9999/v1/embeddings",
            })
            self.assertEqual(module.CFG["sources"], [("notes", str(home / "notes"))])
            self.assertEqual(module.CFG["db_path"], str(home / ".recall/shared.db"))
            self.assertEqual(module.CFG["publish_path"], str(home / "sync/published.db"))
            self.assertEqual(module.CFG["inbox"], str(home / "notes/_inbox"))
            self.assertTrue(module.CFG["read_only"])
            self.assertEqual(module.CFG["retrieval_mode"], "hybrid")
            self.assertEqual(module.CFG["exclude_files"], {"MEMORY.md"})
            self.assertEqual(module.EMBED_URL, "http://localhost:9999/v1/embeddings")

    def test_config_sources_win_while_runtime_env_overrides_role_and_mode(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {
                "sources": [{"label": "config", "path": "~/config-notes"}],
                "read_only": False,
                "retrieval_mode": "vector",
            }, {
                "RECALL_SOURCES": json.dumps({"sources": [{"label": "env", "path": "~/env-notes"}]}),
                "RECALL_READONLY": "true",
                "RECALL_RETRIEVAL_MODE": "hybrid",
            })
            self.assertEqual(module.CFG["sources"][0][0], "config")
            self.assertTrue(module.CFG["read_only"])
            self.assertEqual(module.CFG["retrieval_mode"], "hybrid")

    def test_environment_sources_are_used_when_config_has_none(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {}, {
                "RECALL_SOURCES": json.dumps({"sources": [{"label": "env", "path": "~/env-notes"}]})
            })
            self.assertEqual(module.CFG["sources"][0][0], "env")

    def test_invalid_retrieval_mode_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "retrieval_mode"):
                load_engine(Path(td), {
                    "sources": [{"label": "notes", "path": "~/notes"}],
                    "retrieval_mode": "automatic-magic",
                })

    def test_invalid_read_only_value_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "read_only"):
                load_engine(Path(td), {
                    "sources": [{"label": "notes", "path": "~/notes"}],
                    "read_only": "maybe",
                })

    def test_empty_env_override_does_not_flip_reader_to_writer(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {
                "sources": [{"label": "notes", "path": "~/notes"}],
                "read_only": True,
            }, {
                "RECALL_READONLY": "",
                "RECALL_RETRIEVAL_MODE": "",
                "RECALL_EMBED_URL": "",
            })
            self.assertTrue(module.CFG["read_only"])
            self.assertEqual(module.CFG["retrieval_mode"], "vector")
            self.assertEqual(module.EMBED_URL, "http://localhost:8080/v1/embeddings")

    def test_non_list_sources_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "sources"):
                load_engine(Path(td), {"sources": "~/notes"})

    def test_scalar_sources_entry_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "sources"):
                load_engine(Path(td), {"sources": ["~/notes"]})


class RecallCorpusTests(unittest.TestCase):
    def test_iter_files_excludes_memory_catalog_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / "notes"
            root.mkdir()
            (root / "fact.md").write_text("fact", encoding="utf-8")
            (root / "MEMORY.md").write_text("catalog", encoding="utf-8")
            module = load_engine(home, {"sources": [{"label": "notes", "path": str(root)}]})
            paths = [Path(path).name for _, _, path in module.iter_files()]
            self.assertEqual(paths, ["fact.md"])

    def test_explicit_empty_exclude_files_preserves_catalog_temporarily(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / "notes"
            root.mkdir()
            (root / "MEMORY.md").write_text("catalog", encoding="utf-8")
            module = load_engine(home, {
                "sources": [{"label": "notes", "path": str(root)}],
                "exclude_files": [],
            })
            self.assertEqual([Path(path).name for _, _, path in module.iter_files()], ["MEMORY.md"])


class RecallRoleTests(unittest.TestCase):
    def test_reader_refuses_index_and_publish(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {
                "sources": [{"label": "notes", "path": "~/notes"}],
                "read_only": True,
            })
            for action in (lambda: module.cmd_index(), lambda: module.cmd_publish()):
                with self.assertRaises(SystemExit) as raised:
                    action()
                self.assertEqual(raised.exception.code, 2)

    def test_frontmatter_values_are_json_quoted(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {"sources": [{"label": "notes", "path": "~/notes"}]})
            self.assertEqual(module._yaml_scalar('title: "quoted"'), '"title: \\"quoted\\""')

    def test_sql_literal_escapes_single_quotes(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {"sources": [{"label": "notes", "path": "~/notes"}]})
            self.assertEqual(module._sql_literal("a'b"), "'a''b'")

    def test_portable_citation_prefers_source_relative_path(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {"sources": [{"label": "notes", "path": "~/notes"}]})
            self.assertEqual(module._citation("notes", "/machine/a.md", "folder/a.md"), "notes/folder/a.md")


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.lastrowid = 1

    def execute(self, sql, params=()):
        self.conn.sql.append((sql.strip(), params))
        stripped = sql.strip().lower()
        if "pragma table_info(chunks)" in stripped:
            cols = ["id", "source", "path", "line", "txt", "emb"]
            if self.conn.has_rel:
                cols.insert(3, "rel")
            self._rows = [(i, name, "", 0, None, 0) for i, name in enumerate(cols)]
        else:
            self._rows = []
        return self

    def __iter__(self):
        return iter(getattr(self, "_rows", []))

    def fetchall(self):
        return getattr(self, "_rows", [])

    def fetchone(self):
        rows = getattr(self, "_rows", [])
        return rows[0] if rows else None


class FakeConn:
    def __init__(self, uri, has_rel):
        self.uri = uri
        self.has_rel = has_rel
        self.sql = []
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True


class FakeLibsql:
    def __init__(self, has_rel=True):
        self.has_rel = has_rel
        self.calls = []
        self.last = None

    def connect(self, target, _uri=False):
        self.calls.append((target, _uri))
        self.last = FakeConn(target, self.has_rel)
        return self.last


class RecallDbTests(unittest.TestCase):
    def _engine(self, td, config):
        return load_engine(Path(td), config)

    def test_reader_connects_read_only_uri(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._engine(td, {
                "sources": [{"label": "n", "path": "~/n"}],
                "db_path": "~/.recall/x.db", "read_only": True,
            })
            fake = FakeLibsql()
            with mock.patch.dict(sys.modules, {"libsql": fake}):
                module.connect()
            target, uri = fake.calls[0]
            self.assertTrue(target.startswith("file:") and target.endswith("?mode=ro"))
            self.assertTrue(uri)

    def test_writer_adds_rel_only_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._engine(td, {"sources": [{"label": "n", "path": "~/n"}]})
            for has_rel in (False, True):
                fake = FakeLibsql(has_rel=has_rel)
                with mock.patch.dict(sys.modules, {"libsql": fake}):
                    module.connect()
                altered = any("add column rel" in sql.lower() for sql, _ in fake.last.sql)
                self.assertEqual(altered, not has_rel)

    def test_pre_rel_reader_selects_null_without_alter(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._engine(td, {"sources": [{"label": "n", "path": "~/n"}], "read_only": True})
            fake = FakeLibsql(has_rel=False)
            with mock.patch.dict(sys.modules, {"libsql": fake}):
                con, cur = module.connect()
                cols = module._chunk_select_columns(cur)
            self.assertIn("NULL AS rel", cols)
            self.assertFalse(any("add column" in sql.lower() for sql, _ in fake.last.sql))

    def test_post_rel_reader_selects_real_column(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._engine(td, {"sources": [{"label": "n", "path": "~/n"}], "read_only": True})
            fake = FakeLibsql(has_rel=True)
            with mock.patch.dict(sys.modules, {"libsql": fake}):
                con, cur = module.connect()
                cols = module._chunk_select_columns(cur)
            self.assertEqual(cols, "source,path,rel,line,txt")

    def test_reader_index_and_publish_exit_before_connect(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._engine(td, {
                "sources": [{"label": "n", "path": "~/n"}],
                "read_only": True, "publish_path": "~/pub.db",
            })
            boom = mock.Mock(side_effect=AssertionError("connect must not be called"))
            with mock.patch.dict(sys.modules, {"libsql": mock.Mock(connect=boom)}):
                for action in (module.cmd_index, module.cmd_publish):
                    with self.assertRaises(SystemExit) as raised:
                        action()
                    self.assertEqual(raised.exception.code, 2)

    def test_publish_escapes_quotes_and_replaces_after_vacuum(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            pub = home / "o'dir" / "pub.db"
            module = self._engine(td, {
                "sources": [{"label": "n", "path": "~/n"}],
                "publish_path": str(pub),
            })
            fake = FakeLibsql()
            order = []
            real_replace = os.replace
            def spy_replace(a, b):
                order.append(("replace", a, b))
            with mock.patch.dict(sys.modules, {"libsql": fake}), \
                 mock.patch.object(module.os, "replace", spy_replace), \
                 mock.patch.object(module.os.path, "getsize", lambda p: 0):
                module.cmd_publish()
            vacuums = [sql for sql, _ in fake.last.sql if sql.lower().startswith("vacuum into")]
            self.assertEqual(len(vacuums), 1)
            self.assertIn("'" + str(pub) + ".tmp'", vacuums[0].replace("''", "'").replace("o'dir", "o'dir"))
            self.assertIn("o''dir", vacuums[0])
            self.assertEqual(order, [("replace", str(pub) + ".tmp", str(pub))])

    def test_missing_source_root_aborts_before_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._engine(td, {"sources": [{"label": "n", "path": str(Path(td) / "gone")}]})
            boom = mock.Mock(side_effect=AssertionError("connect must not be called"))
            with mock.patch.dict(sys.modules, {"libsql": mock.Mock(connect=boom)}):
                with self.assertRaises(SystemExit) as raised:
                    module.cmd_index()
                self.assertEqual(raised.exception.code, 2)

    def test_rebuild_rolls_back_on_embed_failure(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / "n"
            root.mkdir()
            (root / "a.md").write_text("body text here", encoding="utf-8")
            module = self._engine(td, {"sources": [{"label": "n", "path": str(root)}]})
            fake = FakeLibsql()
            with mock.patch.dict(sys.modules, {"libsql": fake}), \
                 mock.patch.object(module, "embed", side_effect=OSError("embedder down")):
                with self.assertRaises(OSError):
                    module.cmd_index(rebuild=True)
            self.assertGreaterEqual(fake.last.rolled_back, 1)
            # the only commit is connect()'s schema setup; the rebuild data
            # transaction is rolled back, never committed
            self.assertEqual(fake.last.committed, 1)


class _RecallCursor:
    """Minimal cursor for exercising cmd_recall ranking paths. Vector scan
    returns vec_ids in order; FTS MATCH returns fts_ids; row lookups return a
    synthetic chunk. `rank_raises` forces a damaged-rank FTS error once."""

    def __init__(self, has_rel, vec_ids, fts_ids, rows, rank_raises=False):
        self.has_rel = has_rel
        self.vec_ids = vec_ids
        self.fts_ids = fts_ids
        self.rows = rows
        self.rank_raises = rank_raises
        self._result = []

    def execute(self, sql, params=()):
        s = " ".join(sql.lower().split())
        if "pragma table_info(chunks)" in s:
            cols = ["id", "source", "path", "line", "txt", "emb"]
            if self.has_rel:
                cols.insert(3, "rel")
            self._result = [(i, n, "", 0, None, 0) for i, n in enumerate(cols)]
        elif "order by vector_distance_cos" in s:
            self._result = [(i,) for i in self.vec_ids]
        elif "from fts where fts match" in s and "order by rank" in s:
            if self.rank_raises:
                self.rank_raises = False
                raise __import__("sqlite3").DatabaseError("database disk image is malformed")
            self._result = [(i,) for i in self.fts_ids]
        elif "from fts where fts match" in s:
            self._result = [(i,) for i in self.fts_ids]
        elif "from chunks where id=?" in s:
            self._result = [self.rows[params[0]]]
        elif "count(*)" in s:
            self._result = [(0, 0)]
        else:
            self._result = []
        return self

    def fetchall(self):
        return self._result


def _run_recall(module, cur, mode=None, embed_ok=True):
    con = types.SimpleNamespace(cursor=lambda: cur)
    embed = (mock.Mock(return_value=[0.0] * 768) if embed_ok
             else mock.Mock(side_effect=OSError("embedder down")))
    buf = []
    with mock.patch.object(module, "connect", return_value=(con, cur)), \
         mock.patch.object(module, "embed", embed), \
         mock.patch("builtins.print", lambda *a, **k: buf.append(" ".join(str(x) for x in a))
                    if k.get("file") is None else None):
        module.cmd_recall("some query text", k=3, mode=mode)
    return "\n".join(buf)


class RecallRankingTests(unittest.TestCase):
    def _module(self, td, mode):
        return load_engine(Path(td), {
            "sources": [{"label": "notes", "path": "~/notes"}],
            "retrieval_mode": mode,
        })

    def _rows(self, ids, rel="folder/a.md"):
        return {i: ("notes", "/machine/notes/folder/a.md", rel, 10, f"chunk {i} body")
                for i in ids}

    def test_configured_vector_mode_keeps_vector_order(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, "vector")
            cur = _RecallCursor(True, vec_ids=[5, 6, 7], fts_ids=[9, 6],
                                rows=self._rows([5, 6, 7, 9]))
            out = _run_recall(module, cur)
            first_lines = [ln for ln in out.splitlines() if ln.startswith("[")]
            # vector order 5,6,7 preserved; 9 (fts-only) excluded
            self.assertEqual(len(first_lines), 3)
            self.assertTrue(first_lines[0].startswith("[V+K]") or first_lines[0].startswith("[V]"))

    def test_configured_hybrid_mode_uses_rrf(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, "hybrid")
            # 9 is fts-only but high FTS rank; hybrid must surface it
            cur = _RecallCursor(True, vec_ids=[5, 6], fts_ids=[9, 5],
                                rows=self._rows([5, 6, 9]))
            out = _run_recall(module, cur)
            self.assertIn("notes/folder/a.md:10", out)
            self.assertIn("[K]", out)

    def test_query_flag_overrides_configured_mode(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, "vector")
            cur = _RecallCursor(True, vec_ids=[1], fts_ids=[2, 1],
                                rows=self._rows([1, 2]))
            out = _run_recall(module, cur, mode="hybrid")
            self.assertIn("[K]", out)  # fts-only doc 2 present under forced hybrid

    def test_embedder_down_degrades_to_keyword_only(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, "vector")
            cur = _RecallCursor(True, vec_ids=[], fts_ids=[3, 4],
                                rows=self._rows([3, 4]))
            out = _run_recall(module, cur, embed_ok=False)
            self.assertIn("[K]", out)
            self.assertNotIn("[V", out)

    def test_damaged_fts_rank_retries_unranked(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, "hybrid")
            cur = _RecallCursor(True, vec_ids=[1], fts_ids=[2],
                                rows=self._rows([1, 2]), rank_raises=True)
            out = _run_recall(module, cur)
            self.assertIn("folder/a.md:10", out)

    def test_both_arms_unavailable_prints_no_matches(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, "vector")
            cur = _RecallCursor(True, vec_ids=[], fts_ids=[], rows={})
            out = _run_recall(module, cur, embed_ok=False)
            self.assertIn("(no matches)", out)

    def test_null_rel_uses_fallback_citation(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, "vector")
            rows = {1: ("notes", os.path.join(str(Path(td)), "notes", "a.md"), None, 4, "body")}
            cur = _RecallCursor(False, vec_ids=[1], fts_ids=[], rows=rows)
            out = _run_recall(module, cur)
            self.assertIn("notes/a.md:4", out)


class RecallAddTests(unittest.TestCase):
    def setUp(self):
        # cmd_add prints the created path to stdout by design; keep it out of the
        # test runner output.
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def _module(self, td, **extra):
        cfg = {"sources": [{"label": "notes", "path": str(Path(td) / "notes")}],
               "inbox": str(Path(td) / "notes" / "_inbox")}
        cfg.update(extra)
        return load_engine(Path(td), cfg)

    def test_empty_text_exits_two(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td)
            with self.assertRaises(SystemExit) as raised:
                module.cmd_add("   ")
            self.assertEqual(raised.exception.code, 2)

    def test_reader_writes_note_and_never_indexes(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, read_only=True)
            with mock.patch.object(module, "cmd_index",
                                   side_effect=AssertionError("reader must not index")):
                path = module.cmd_add("a durable fact", source="cli")
            self.assertTrue(os.path.exists(path))
            self.assertEqual(len(list((Path(td) / "notes" / "_inbox").iterdir())), 1)

    def test_writer_indexes_then_publishes_only_with_flag(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td, publish_path=str(Path(td) / "pub.db"))
            with mock.patch.object(module, "cmd_index") as idx, \
                 mock.patch.object(module, "cmd_publish") as pub:
                module.cmd_add("fact one")
                idx.assert_called_once()
                pub.assert_not_called()
                module.cmd_add("fact two", publish=True)
                pub.assert_called_once()

    def test_quoted_source_and_title_produce_valid_frontmatter(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td)
            with mock.patch.object(module, "cmd_index"):
                path = module.cmd_add("body", source='we: "x"', title='t: "y"')
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn('source: "we: \\"x\\""', text)
            self.assertIn('title: "t: \\"y\\""', text)

    def test_note_saved_even_when_indexing_embed_fails(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td)
            with mock.patch.object(module, "cmd_index",
                                   side_effect=OSError("embedder down")):
                path = module.cmd_add("resilient capture")
            self.assertTrue(os.path.exists(path))


class RecallDispatchTests(unittest.TestCase):
    def _module(self, td):
        return load_engine(Path(td), {"sources": [{"label": "n", "path": "~/n"}]})

    def test_index_publish_only_when_changed_or_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td)
            with mock.patch.object(module, "cmd_index", return_value=0) as idx, \
                 mock.patch.object(module, "cmd_publish") as pub:
                module._cli(["index", "--publish"])
                pub.assert_not_called()
                idx.return_value = 3
                module._cli(["index", "--publish"])
                pub.assert_called_once()
            with mock.patch.object(module, "cmd_index", return_value=0), \
                 mock.patch.object(module, "cmd_publish") as pub:
                module._cli(["index", "--rebuild", "--publish"])
                pub.assert_called_once()

    def test_add_forwards_every_argument(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td)
            with mock.patch.object(module, "cmd_add") as add:
                module._cli(["add", "some", "fact", "--title", "T", "--source", "chat", "--publish"])
            add.assert_called_once_with("some fact", source="chat", title="T", publish=True)

    def test_vector_flag_reaches_cmd_recall(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td)
            with mock.patch.object(module, "cmd_recall") as rec:
                module._cli(["what", "is", "this", "--vector"])
            rec.assert_called_once_with("what is this", k=5, mode="vector")

    def test_vector_and_hybrid_together_exit_two(self):
        with tempfile.TemporaryDirectory() as td:
            module = self._module(td)
            with self.assertRaises(SystemExit) as raised:
                module._cli(["q", "--vector", "--hybrid"])
            self.assertEqual(raised.exception.code, 2)


class RecallStatsTests(unittest.TestCase):
    def test_stats_sanitizes_endpoint_and_reports_role_mode(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {
                "sources": [{"label": "n", "path": "~/n"}],
                "retrieval_mode": "hybrid",
                "read_only": True,
                "embed_url": "https://user:secret@embed.example.com:8443/v1/embeddings?token=abc#frag",
            })
            cur = _RecallCursor(True, [], [], {})
            con = types.SimpleNamespace(cursor=lambda: cur)
            buf = []
            with mock.patch.object(module, "connect", return_value=(con, cur)), \
                 mock.patch.object(module.os.path, "exists", return_value=False), \
                 mock.patch("builtins.print", lambda *a, **k: buf.append(" ".join(str(x) for x in a))):
                module.cmd_stats()
            out = "\n".join(buf)
            self.assertIn("role=reader", out)
            self.assertIn("retrieval_mode=hybrid", out)
            self.assertIn("embedder=https://embed.example.com:8443/v1/embeddings", out)
            self.assertNotIn("secret", out)
            self.assertNotIn("token=abc", out)
            self.assertNotIn("frag", out)


class BenchPathMatchTests(unittest.TestCase):
    def test_benchmark_rows_and_citations_stay_path_matchable(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_engine(Path(td), {"sources": [{"label": "notes", "path": "~/notes"}]})
            # old-style benchmark row: (id, absolute path)
            old_path = "/indexer/notes/career/resume_facts.md"
            self.assertIn("career/resume_facts.md", old_path)
            # engine citation row for the same chunk once `rel` exists
            cite = module._citation("notes", old_path, "career/resume_facts.md")
            self.assertEqual(cite, "notes/career/resume_facts.md")
            match_text = old_path + "\n" + cite
            self.assertIn("career/resume_facts.md", match_text)
            # pre-rel row still matches via the home-relative fallback
            home_row = os.path.join(module.HOME, "notes", "career", "resume_facts.md")
            fallback = module._citation("notes", home_row, None)
            self.assertIn("career/resume_facts.md", fallback)


def _fake_repo(root: Path, engine_body: str) -> Path:
    eng_dir = root / "tools" / "recall"
    eng_dir.mkdir(parents=True)
    (eng_dir / "recall.py").write_text(engine_body, encoding="utf-8")
    return root


_ENGINE_MAIN = (
    "import sys\n"
    "def cmd_recall(*a, **k):\n"
    "    return 'engine-ok'\n"
    "SENTINEL = 42\n"
    "if __name__ == '__main__':\n"
    "    sys.stderr.write('ENGINE MAIN argv=%r\\n' % (sys.argv,))\n"
)


class LauncherMainTests(unittest.TestCase):
    def _run_main(self, home: Path, repo: Path, argv=("stats",), extra_env=None):
        env = {"HOME": str(home), "AGENT_RULES_HOME": str(repo)}
        env.update(extra_env or {})
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(sys, "argv", ["recall.py", *argv]), \
             contextlib.redirect_stderr(err), \
             contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(LAUNCHER), run_name="__main__")
        return err.getvalue()

    def test_missing_engine_exits_two_with_path(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            repo = Path(td) / "empty-repo"
            home.mkdir()
            repo.mkdir()
            err = io.StringIO()
            with mock.patch.dict(os.environ, {"HOME": str(home), "AGENT_RULES_HOME": str(repo)}, clear=True), \
                 mock.patch.object(sys, "argv", ["recall.py", "stats"]), \
                 contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(str(LAUNCHER), run_name="__main__")
            self.assertEqual(raised.exception.code, 2)
            self.assertIn(str(repo / "tools" / "recall" / "recall.py"), err.getvalue())

    def test_reexecs_under_recall_venv_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            repo = _fake_repo(Path(td) / "repo", _ENGINE_MAIN)
            venv_py = home / ".recall" / ".venv" / "bin" / "python3"
            venv_py.parent.mkdir(parents=True)
            venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch("os.execv") as execv:
                self._run_main(home, repo, argv=("index", "--publish"))
            execv.assert_called_once()
            called_py, call_argv = execv.call_args[0]
            self.assertEqual(called_py, str(venv_py))
            self.assertEqual(call_argv[1:], [str(repo / "tools" / "recall" / "recall.py"),
                                             "index", "--publish"])

    def test_reexecs_even_when_venv_python_is_symlink_to_base(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            repo = _fake_repo(Path(td) / "repo", _ENGINE_MAIN)
            bindir = home / ".recall" / ".venv" / "bin"
            bindir.mkdir(parents=True)
            (bindir / "python3").symlink_to(sys.executable)  # venv python -> base
            with mock.patch("os.execv") as execv:
                self._run_main(home, repo)
            execv.assert_called_once()

    def test_no_recursion_when_prefix_is_recall_venv(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            repo = _fake_repo(Path(td) / "repo", _ENGINE_MAIN)
            venv_root = home / ".recall" / ".venv"
            (venv_root / "bin").mkdir(parents=True)
            (venv_root / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch("os.execv") as execv, \
                 mock.patch.object(sys, "prefix", str(venv_root)):
                err = self._run_main(home, repo)
            execv.assert_not_called()
            self.assertIn("ENGINE MAIN", err)  # ran the engine in-process instead

    def test_agent_rules_home_selects_engine_root(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            repo = _fake_repo(Path(td) / "custom", _ENGINE_MAIN)
            with mock.patch("os.execv"):
                err = self._run_main(home, repo)
            self.assertIn("ENGINE MAIN", err)


class LauncherImportTests(unittest.TestCase):
    def test_import_exports_engine_namespace_without_running_cli(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            repo = _fake_repo(Path(td) / "repo", _ENGINE_MAIN)
            name = f"launcher_test_{uuid.uuid4().hex}"
            spec = importlib.util.spec_from_file_location(name, LAUNCHER)
            module = importlib.util.module_from_spec(spec)
            err = io.StringIO()
            with mock.patch.dict(os.environ,
                                 {"HOME": str(home), "AGENT_RULES_HOME": str(repo)}, clear=True), \
                 contextlib.redirect_stderr(err):
                assert spec.loader is not None
                spec.loader.exec_module(module)
            self.assertEqual(module.cmd_recall(), "engine-ok")
            self.assertEqual(module.SENTINEL, 42)
            self.assertNotIn("ENGINE MAIN", err.getvalue())
