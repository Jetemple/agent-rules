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
