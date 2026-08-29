import importlib.util
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
