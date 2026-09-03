# Recall Upstream and Safe Runtime Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Make the public `agent-rules` recall engine feature-complete with the proven local reader/writer implementation, then migrate `~/.recall` to a stable launcher without overwriting private state or silently changing retrieval.

**Architecture:** `tools/recall/recall.py` becomes the canonical generic engine. Device-specific corpus paths, database paths, reader/writer role, embedder endpoint, retrieval mode, inbox, and temporary catalog inclusion remain in `~/.recall/config.json`. A tiny copied launcher at `~/.recall/recall.py` executes the canonical engine through the device-local virtualenv, avoiding both a fragile absolute symlink and a second drifting engine copy.

**Tech Stack:** Python 3 standard library, `libsql`, SQLite/FTS5, llama.cpp's OpenAI-compatible embeddings endpoint, `unittest`, Bash, GitHub Actions, Markdown.

## Global Constraints

- Preserve the existing uncommitted `workflows/wrap/SKILL.md`; this plan does not modify it.
- Never overwrite or delete the existing `~/.recall/recall.py`; checksum and back it up before the migration gate.
- Keep `~/.recall/config.json`, databases, benchmark labels, corpus paths, machine roles, and embedder details out of Git.
- Keep the public repository free of personal names, employer references, hardcoded home paths, private corpus text, and credentials.
- Default `exclude_files` to `["MEMORY.md"]` for new installations, but preserve current retrieval during migration with a private `exclude_files: []` override until the separate catalog-migration plan is complete.
- Preserve vector mode as the public backward-compatible default; configure hybrid mode privately on corpora where its benchmark wins.
- Reader mode must never index, rebuild, or publish. `add` intentionally may write a plain Markdown intake note to the configured synced inbox, because the role protects the derived database rather than the source corpus; it must never mutate the reader's database.
- Roll out schema changes writer-first: upgrade and rebuild/publish on the writer before replacing any reader launcher. The engine must still tolerate a pre-`rel` snapshot during the transition.
- Never run benchmarks against private labels/configuration from a generic test step. CI and pre-migration smoke tests use synthetic labels, a scratch `HOME`, a scratch corpus, and a scratch database. Private parity evidence stays in a mode-700 directory under `~/.recall` and is deleted after comparison.
- No commit, push, PR mutation, merge, or release is authorized by this plan. Before every listed commit command, stop and obtain explicit confirmation for the repository, branch, action, and exact diff.
- Run all tests with a scratch `HOME` and `XDG_CONFIG_HOME="$HOME/.config"` whenever home configuration is involved.

---

## File Structure

### Public repository

- Create `tools/recall/test_recall.py`: standard-library unit tests for config, corpus walking, reader safety, publishing helpers, citations, frontmatter, retrieval-mode selection, and launcher behavior.
- Create `tools/recall/test_recall_integration.py`: real-libSQL, synthetic-corpus CLI smoke test using a scratch home and local fake embedding server.
- Create `tools/recall/launcher.py`: stable device-side shim that locates the public engine and runs it through `~/.recall/.venv`.
- Modify `tools/recall/recall.py`: canonical engine with reader/writer roles, publish/add commands, relative citations, configurable retrieval, FTS recovery, and catalog exclusion.
- Modify `tools/recall/config.example.json`: complete generic configuration schema.
- Modify `tools/recall/README.md`: public behavior, migration, roles, retrieval selection, and failure semantics.
- Modify `docs/memory-and-recall.md`: source-of-truth model and safe deployment contract.
- Modify `docs/setup.md`: fresh setup and migration instructions.
- Modify `setup/install.sh`: seed the stable launcher as `~/.recall/recall.py` instead of copying the engine there.
- Modify `setup/doctor.sh`: distinguish launcher health, engine availability, and private state health.
- Modify `setup/test-fresh-install.sh`: prove fresh install, copy-once launcher stability, and engine resolution.
- Modify `.github/workflows/ci.yml`: execute recall unit tests.

### Private runtime, migration gate only

- Preserve `~/.recall/recall.py.pre-upstream`: exact backup of the working personalized engine.
- Modify `~/.recall/config.json`: add generic fields needed to preserve current behavior. This file remains untracked and must never appear in a diff or report.
- Replace `~/.recall/recall.py` with a copy of `tools/recall/launcher.py` only after parity gates pass and the user explicitly approves this private runtime mutation.

---

### Task 1: Add a hermetic recall contract test suite

**Files:**
- Create: `tools/recall/test_recall.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: importable functions from `tools/recall/recall.py` and `tools/recall/launcher.py`
- Produces: `python3 -m unittest discover -s tools/recall -p 'test_*.py' -v`

- [ ] **Step 1: Write the failing test loader and config tests**

Create `tools/recall/test_recall.py` with a unique-module loader so each test can supply a fresh fake `HOME` and environment:

```python
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
```

- [ ] **Step 2: Add failing corpus, role, and formatting tests**

Append tests with these exact contracts:

```python
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
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```sh
python3 -m unittest discover -s tools/recall -p 'test_*.py' -v
```

Expected: failures for missing `load_config()` fields, `exclude_files`, `_yaml_scalar`, `_sql_literal`, `_citation`, reader refusal, and `launcher.py`.

- [ ] **Step 4: Register the test in CI**

Add this step to `.github/workflows/ci.yml` under `config-contracts`:

```yaml
      - name: Verify recall engine contracts
        run: python3 -m unittest discover -s tools/recall -p 'test_*.py' -v
```

- [ ] **Step 5: Review before commit**

Run:

```sh
git diff --check
git diff -- tools/recall/test_recall.py .github/workflows/ci.yml
```

Expected: only the failing characterization suite and CI registration.

- [ ] **Step 6: Commit only after explicit confirmation**

```sh
git add tools/recall/test_recall.py .github/workflows/ci.yml
git commit -m "test(recall): define shared-runtime contracts"
```

---

### Task 2: Upstream generic configuration and corpus selection

**Files:**
- Modify: `tools/recall/recall.py:1-175`
- Modify: `tools/recall/config.example.json`
- Test: `tools/recall/test_recall.py`

**Interfaces:**
- Produces `load_config() -> dict[str, object]`
- Produces `CFG`, `SOURCES`, `DB_PATH`, `PUBLISH_PATH`, `READ_ONLY`, `RETRIEVAL_MODE`, `EXCLUDE_FILES`
- Changes `iter_files()` to yield `(source, root, absolute_path)`

- [ ] **Step 1: Replace `load_sources()` with validated `load_config()`**

Implement these fields and precedence:

```python
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
```

After defining `load_config()`, initialize globals through this explicit boundary so CLI execution exits 2 while test/library imports still expose the underlying exception:

```python
try:
    CFG = load_config()
except (json.JSONDecodeError, OSError, ValueError) as error:
    if __name__ == "__main__":
        print(f"recall: invalid configuration: {error}", file=sys.stderr)
        raise SystemExit(2)
    raise
```

Do not silently substitute generic defaults after a malformed real config.

- [ ] **Step 2: Remove import-time `libsql` bootstrapping**

Delete `_ensure_libsql()` and import `libsql` only inside `connect()`. The launcher owns virtualenv selection; the engine must remain importable for unit tests.

- [ ] **Step 3: Update the file walker**

Implement:

```python
def iter_files():
    for source, root in SOURCES:
        if not os.path.isdir(root):
            continue
        for directory, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in EXCLUDE_DIRS]
            for name in sorted(files):
                if name.endswith(".md") and name not in EXCLUDE_FILES:
                    yield source, root, os.path.join(directory, name)
```

Keep `_scratch`, `_archive`, `.git`, `node_modules`, `.obsidian`, and `_recall` excluded.

- [ ] **Step 4: Expand the public example configuration**

Replace `tools/recall/config.example.json` with valid generic JSON:

```json
{
  "sources": [
    { "label": "memory", "path": "~/notes/memory" },
    { "label": "vault", "path": "~/notes/vault" }
  ],
  "db_path": "~/.recall/memory.db",
  "publish_path": null,
  "read_only": false,
  "inbox": "~/notes/memory/_inbox",
  "retrieval_mode": "vector",
  "exclude_files": ["MEMORY.md"],
  "embed_url": "http://localhost:8080/v1/embeddings",
  "embed_model": "ggml-org/embeddinggemma-300M-GGUF:Q8_0"
}
```

- [ ] **Step 5: Run focused tests**

```sh
python3 -m unittest tools/recall/test_recall.py -v
```

Expected: config and corpus tests pass; role/formatting tests remain failing until later tasks.

- [ ] **Step 6: Commit only after explicit confirmation**

```sh
git add tools/recall/recall.py tools/recall/config.example.json tools/recall/test_recall.py
git commit -m "feat(recall): add portable runtime configuration"
```

---

### Task 3: Add reader/writer database roles and atomic publishing

**Files:**
- Modify: `tools/recall/recall.py:140-320`
- Test: `tools/recall/test_recall.py`

**Interfaces:**
- `connect(read_only: bool | None = None) -> tuple[Connection, Cursor]`
- `cmd_index(rebuild: bool = False) -> int`
- `cmd_publish() -> None`
- `_refuse_if_readonly(action: str) -> None`
- `_chunks_has_rel(cursor) -> bool`
- `_chunk_select_columns(cursor) -> str`
- `_sql_literal(value: str) -> str`

- [ ] **Step 1: Make schema migration and reader connections explicit**

Implement reader mode with libSQL URI mode and writer mode with an idempotent `rel` migration:

```python
def connect(read_only=None):
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
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(chunks)").fetchall()}
    if "rel" not in columns:
        cursor.execute("ALTER TABLE chunks ADD COLUMN rel TEXT")
    cursor.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS fts
        USING fts5(txt, content='chunks', content_rowid='id')""")
    cursor.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, hash TEXT)")
    connection.commit()
    return connection, cursor
```

Do not catch every `ALTER TABLE` exception; inspect schema first so genuine database errors propagate. Add transition helpers that work on read-only pre-`rel` snapshots:

```python
def _chunks_has_rel(cursor):
    return "rel" in {row[1] for row in cursor.execute("PRAGMA table_info(chunks)").fetchall()}


def _chunk_select_columns(cursor):
    return "source,path,rel,line,txt" if _chunks_has_rel(cursor) else "source,path,NULL AS rel,line,txt"
```

Every read path that selects `rel` must use `_chunk_select_columns(cursor)`. Readers never alter schema. Writers migrate the column before writing new rows.

- [ ] **Step 2: Enforce reader role before mutations**

Implement:

```python
def _refuse_if_readonly(action):
    if READ_ONLY:
        print(f"recall: this machine is read_only; refusing to {action}.", file=sys.stderr)
        raise SystemExit(2)
```

Call it before `cmd_index()` and `cmd_publish()` acquire a writable connection.

- [ ] **Step 3: Validate every corpus root before indexing**

A missing configured source must abort before stale-file deletion. Implement:

```python
def _validate_source_roots():
    missing = [(label, root) for label, root in SOURCES if not os.path.isdir(root)]
    if missing:
        for label, root in missing:
            print(f"recall: source root missing for {label}: {root}", file=sys.stderr)
        raise SystemExit(2)
```

Call `_validate_source_roots()` before opening a writer transaction. Do not silently treat an unavailable synced volume as an empty corpus.

- [ ] **Step 4: Preserve relative citations and make rebuild rollback-safe**

Update `cmd_index()` for the new walker tuple and store `rel = os.path.relpath(path, root)`. Return the number of changed files. Incremental indexing may retain per-file commits. Rebuild must use one explicit transaction so an embedding, filesystem, or database interruption restores the previous index:

```python
_validate_source_roots()
connection, cursor = connect()
if rebuild:
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("INSERT INTO fts(fts) VALUES (?)", ("delete-all",))
        cursor.execute("DELETE FROM chunks")
        cursor.execute("DELETE FROM files")
        changed, chunk_count = _index_all_files(cursor, commit_each=False)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return changed
return _index_all_files(cursor, commit_each=True)
```

Extract the existing loop into `_index_all_files(cursor, commit_each)`; it may commit after each changed file only when `commit_each` is true. Add tests proving a missing root exits before deletion and a forced embed failure during rebuild calls `rollback()` without `commit()`.

- [ ] **Step 5: Implement safe atomic publishing**

Add:

```python
def _sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def cmd_publish():
    _refuse_if_readonly("publish")
    if not PUBLISH_PATH:
        print("recall: no publish_path configured.", file=sys.stderr)
        raise SystemExit(2)
    os.makedirs(os.path.dirname(PUBLISH_PATH), exist_ok=True)
    temporary = PUBLISH_PATH + ".tmp"
    if os.path.exists(temporary):
        os.remove(temporary)
    connection, cursor = connect()
    cursor.execute(f"VACUUM INTO {_sql_literal(temporary)}")
    connection.commit()
    connection.close()
    os.replace(temporary, PUBLISH_PATH)
```

A failed `VACUUM INTO` must leave the current published snapshot untouched.

- [ ] **Step 6: Add fake-libSQL tests**

Use a `FakeLibsql` object injected through `mock.patch.dict(sys.modules, {"libsql": fake})` to assert:

- reader connects with `file:<db>?mode=ro` and `_uri=True`
- writer creates `rel` only when absent
- pre-`rel` reader selects `NULL AS rel` without attempting `ALTER TABLE`
- post-migration reader selects the actual `rel` column
- reader index/publish exits 2 before any connection
- publish escapes quote-containing paths
- publish calls `os.replace(temp, destination)` only after successful vacuum

Do not require a live embedder or native libSQL in CI.

- [ ] **Step 7: Run tests**

```sh
python3 -m unittest tools/recall/test_recall.py -v
```

Expected: config, corpus, role, source-root, rollback, pre-`rel`, SQL, and publishing tests pass.

- [ ] **Step 8: Commit only after explicit confirmation**

```sh
git add tools/recall/recall.py tools/recall/test_recall.py
git commit -m "feat(recall): support reader writer snapshots"
```

---

### Task 4: Upstream add, portable output, resilient FTS, and configurable ranking

**Files:**
- Modify: `tools/recall/recall.py:250-end`
- Modify: `tools/recall/bench_quality.py`
- Modify: `tools/recall/requirements.txt`
- Modify: `.github/workflows/ci.yml`
- Test: `tools/recall/test_recall.py`
- Create: `tools/recall/test_recall_integration.py`

**Interfaces:**
- `cmd_add(text: str, source: str = "cli", title: str | None = None, publish: bool = False) -> str`
- `_yaml_scalar(value: str) -> str`
- `_citation(source: str, path: str, rel: str | None) -> str`
- `cmd_recall(q: str, k: int = 5, pool: int = 20, mode: str | None = None) -> None`
- `cmd_stats() -> None`, exposing sanitized effective role, retrieval mode, and embedder endpoint
- CLI commands: `index [--rebuild] [--publish]`, `publish`, `add <text> [--title] [--source] [--publish]`, query `[--vector|--hybrid]`, and `stats`

- [ ] **Step 1: Implement safe intake-note writing**

Use JSON strings as valid YAML scalars:

```python
def _yaml_scalar(value):
    return json.dumps(str(value), ensure_ascii=False)
```

`cmd_add()` must:

- reject empty text with exit 2
- create the configured inbox
- generate a timestamp plus six-character SHA1 filename
- quote `source` and `title` frontmatter values through `_yaml_scalar`
- always save the Markdown note before attempting index or publish
- on readers, report deferred indexing without touching the DB
- on writers, index immediately and optionally publish
- return and print the created path

Catch only embedder availability errors around immediate indexing. Do not catch filesystem, schema, or permission failures.

- [ ] **Step 2: Implement portable citation formatting**

```python
def _citation(source, path, rel):
    return f"{source}/{rel}" if rel else os.path.relpath(path, HOME)
```

When reading an older row whose `rel` is null, fall back to the old home-relative path rather than failing.

- [ ] **Step 3: Preserve both measured retrieval modes**

Change `cmd_recall()` to select `mode or RETRIEVAL_MODE`:

- `vector`: vector order is authoritative; keyword arm is still computed for tags and fallback
- `hybrid`: reciprocal-rank fusion combines vector and FTS ranks
- embedder unavailable: keyword-only
- ranked FTS unavailable: retry unranked FTS
- both arms unavailable: print `(no matches)` and return cleanly

The CLI must retain `--hybrid` as a backward-compatible one-query override and add `--vector`. Reject using both flags together.

- [ ] **Step 4: Implement the documented CLI dispatch exactly**

Use one explicit dispatch block:

```python
parser.add_argument("--vector", action="store_true")
parser.add_argument("--hybrid", action="store_true")
parser.add_argument("--publish", action="store_true")
parser.add_argument("--source", default="cli")
parser.add_argument("--title")
args = parser.parse_args()
if args.vector and args.hybrid:
    parser.error("--vector and --hybrid are mutually exclusive")
mode = "vector" if args.vector else ("hybrid" if args.hybrid else None)

if args.cmd_or_query == "index":
    changed = cmd_index(rebuild=args.rebuild)
    if args.publish and (changed > 0 or args.rebuild):
        cmd_publish()
elif args.cmd_or_query == "publish":
    cmd_publish()
elif args.cmd_or_query == "add":
    cmd_add(" ".join(args.rest), source=args.source, title=args.title, publish=args.publish)
elif args.cmd_or_query == "stats":
    cmd_stats()
else:
    cmd_recall(" ".join([args.cmd_or_query, *args.rest]), k=args.k, mode=mode)
```

Add dispatch tests proving `index --publish` publishes only when `cmd_index()` returns a positive count or `--rebuild` is present; `add --title --publish` forwards every argument; and `--vector` reaches `cmd_recall(mode="vector")`.

- [ ] **Step 5: Expose sanitized effective configuration in stats**

Add:

```python
from urllib.parse import urlsplit


def _display_endpoint(url):
    parsed = urlsplit(url)
    host = parsed.hostname or "unknown"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}{parsed.path}"
```

`cmd_stats()` must print `role=reader|writer`, `retrieval_mode=vector|hybrid`, and `embedder=<sanitized endpoint>` without userinfo, query strings, fragments, tokens, or HTTP headers.

- [ ] **Step 6: Make benchmark imports use the same configured DB safely**

Keep `bench_quality.py` importing `recall`, but make its result path handling tolerate the added `rel` column without changing private label formats. Add a unit test proving both old `(id, path)` benchmark rows and engine citation rows remain path-matchable.

- [ ] **Step 7: Extend CLI tests**

Patch `embed`, `connect`, and `cmd_*` dependencies to verify:

- `add` on reader writes one note and never calls `cmd_index`
- `add` on writer calls `cmd_index`, then `cmd_publish` only with `--publish`
- source/title values containing quotes produce valid quoted frontmatter
- configured hybrid mode uses RRF
- configured vector mode keeps vector ordering
- `--hybrid --vector` exits 2
- null or absent `rel` uses the fallback citation
- `stats` sanitizes an endpoint containing userinfo, query, and fragment

- [ ] **Step 8: Pin libSQL and add a synthetic real-CLI integration test**

Pin the version already validated by the existing runtime:

```text
libsql==0.1.11
```

Create `tools/recall/test_recall_integration.py`. It must use `tempfile.TemporaryDirectory()` for `HOME`, corpus, config, database, publish destination, labels, and outputs. Start a loopback `http.server.ThreadingHTTPServer` that returns deterministic 768-element embeddings; never read `~/.recall`, private labels, or the live database. Through subprocess calls to the actual `recall.py`, assert:

1. `index --publish` creates a scratch DB and published snapshot.
2. A second unchanged `index --publish` does not replace the published snapshot.
3. `add --title "Synthetic title" --publish "synthetic durable fact"` writes only inside the scratch inbox and refreshes the scratch publish file.
4. A hybrid query returns the expected synthetic source-relative citation.
5. `--vector` executes successfully and reports a source-relative citation.
6. `stats` reports writer role, configured retrieval mode, and sanitized loopback endpoint.
7. A forced embedding-server failure during `index --rebuild` leaves the prior scratch DB queryable.
8. A missing scratch corpus root exits 2 without deleting prior indexed rows.

The test must set both `HOME=<scratch>` and `XDG_CONFIG_HOME=<scratch>/.config` in every subprocess environment.

- [ ] **Step 9: Install the pinned dependency in CI and run only synthetic tests**

Add Python setup before recall tests in `.github/workflows/ci.yml`:

```yaml
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install recall test dependency
        run: python3 -m pip install -r tools/recall/requirements.txt
      - name: Verify recall engine contracts
        run: python3 -m unittest discover -s tools/recall -p 'test_*.py' -v
```

Run locally:

```sh
SCRATCH_HOME="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_HOME"' EXIT
HOME="$SCRATCH_HOME" XDG_CONFIG_HOME="$SCRATCH_HOME/.config" \
  python3 -m unittest discover -s tools/recall -p 'test_*.py' -v
```

Expected: unit and real-libSQL integration tests pass using only synthetic scratch data. No benchmark JSON or private query text is written to `/tmp`.

- [ ] **Step 10: Commit only after explicit confirmation**

```sh
git add .github/workflows/ci.yml tools/recall/recall.py tools/recall/bench_quality.py \
  tools/recall/requirements.txt tools/recall/test_recall.py tools/recall/test_recall_integration.py
git commit -m "feat(recall): upstream portable hybrid workflows"
```

---

### Task 5: Add the stable launcher and safe fresh-install contract

**Files:**
- Create: `tools/recall/launcher.py`
- Modify: `setup/install.sh:205-216`
- Modify: `setup/doctor.sh:185-195`
- Modify: `setup/test-fresh-install.sh:120-205`
- Test: `tools/recall/test_recall.py`

**Interfaces:**
- `AGENT_RULES_HOME` optionally overrides the canonical checkout, defaulting to `~/.agent-rules`
- `~/.recall/.venv/bin/python3` remains device-local
- `~/.recall/recall.py` is a copied stable launcher, not a copied engine and not an absolute symlink

- [ ] **Step 1: Write launcher tests first**

Test these cases using a scratch `HOME` and fake engine:

- missing engine exits 2 with the expected path
- direct execution re-execs under `~/.recall/.venv/bin/python3` when available
- a virtualenv interpreter implemented as a symlink to the base Python still re-execs when `sys.prefix` is outside `~/.recall/.venv`
- execution does not recurse when `sys.prefix` already equals the virtualenv root
- `AGENT_RULES_HOME` changes the engine root
- import from an installed benchmark exports engine functions without executing the CLI

- [ ] **Step 2: Implement `tools/recall/launcher.py`**

```python
#!/usr/bin/env python3
import os
from pathlib import Path
import runpy
import sys

HOME = Path.home()
REPO = Path(os.environ.get("AGENT_RULES_HOME", HOME / ".agent-rules")).expanduser()
ENGINE = REPO / "tools" / "recall" / "recall.py"
VENV_ROOT = HOME / ".recall" / ".venv"
VENV_PYTHON = VENV_ROOT / "bin" / "python3"


def _require_engine():
    if not ENGINE.is_file():
        print(f"recall: canonical engine not found at {ENGINE}", file=sys.stderr)
        raise SystemExit(2)


def _export_engine_namespace():
    _require_engine()
    namespace = runpy.run_path(str(ENGINE), run_name="recall_engine")
    globals().update({key: value for key, value in namespace.items()
                      if not key.startswith("__")})


if __name__ == "__main__":
    _require_engine()
    # Virtualenv interpreters commonly symlink to the base binary on macOS, so
    # comparing resolved executable paths incorrectly reports that base Python is
    # already inside the venv. sys.prefix retains the active environment identity.
    in_recall_venv = Path(sys.prefix).resolve() == VENV_ROOT.resolve()
    if VENV_PYTHON.is_file() and not in_recall_venv:
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(ENGINE), *sys.argv[1:]])
    runpy.run_path(str(ENGINE), run_name="__main__")
else:
    _export_engine_namespace()
```

- [ ] **Step 3: Seed the launcher on fresh installs**

Change only the `recall.py` source mapping in `setup/install.sh`:

```sh
copy_once "$REPO/tools/recall/launcher.py" "$HOME/.recall/recall.py"
```

Continue seeding `recall`, `requirements.txt`, examples, and benchmark helpers. Existing real `~/.recall/recall.py` must remain untouched.

- [ ] **Step 4: Update doctor checks**

Doctor must report separately:

- launcher present and executable
- canonical engine present
- local `.venv` present
- private config present
- database present when configured

Use checksum comparison only for the public launcher, never private config:

```sh
launcher="$HOME/.recall/recall.py"
canonical_launcher="$REPO/tools/recall/launcher.py"
if [ -x "$launcher" ] && cmp -s "$launcher" "$canonical_launcher"; then
  echo "ok: recall launcher matches canonical launcher"
elif [ -e "$launcher" ]; then
  echo "warn: recall launcher/runtime differs; preserve it and run the documented migration gate"
  notinstalled=1
else
  echo "warn: recall launcher absent (run ./setup/install.sh)"
  notinstalled=1
fi
[ -f "$REPO/tools/recall/recall.py" ] \
  && echo "ok: canonical recall engine present" \
  || { echo "FAIL: canonical recall engine missing"; fail=1; }
```

Doctor must not compare or reveal private config values.

- [ ] **Step 5: Update fresh-install assertions**

Replace the old “custom engine divergence survives” fixture with:

1. installed `~/.recall/recall.py` equals `tools/recall/launcher.py`
2. canonical engine remains in the repo
3. second install preserves a deliberate launcher-local edit because `copy_once` is still non-destructive
4. doctor warns about the edited launcher but does not overwrite it

The installer must never adopt or overwrite a differing pre-existing runtime automatically.

- [ ] **Step 6: Run focused setup tests**

```sh
python3 -m unittest tools/recall/test_recall.py -v
bash setup/test-fresh-install.sh
bash setup/test-workflows.sh
bash setup/test-compaction-config.sh
```

Expected: all tests pass and no real home files are touched.

- [ ] **Step 7: Commit only after explicit confirmation**

```sh
git add tools/recall/launcher.py tools/recall/test_recall.py setup/install.sh setup/doctor.sh setup/test-fresh-install.sh
git commit -m "feat(recall): install stable canonical launcher"
```

---

### Task 6: Document the public engine and migration boundary

**Files:**
- Modify: `tools/recall/README.md`
- Modify: `docs/memory-and-recall.md`
- Modify: `docs/setup.md`
- Modify: `README.md`

**Interfaces:**
- Public docs describe only generic paths and examples
- Private values remain exclusively in `~/.recall/config.json`

- [ ] **Step 1: Rewrite the engine usage table**

Document these commands exactly:

```sh
python3 ~/.recall/recall.py "natural-language query"
python3 ~/.recall/recall.py index
python3 ~/.recall/recall.py index --publish
python3 ~/.recall/recall.py publish
python3 ~/.recall/recall.py add "durable fact" --title "short title"
python3 ~/.recall/recall.py stats
```

Explain reader, writer, and standalone roles. State that reader `add` writes a Markdown intake note but does not update the reader database.

- [ ] **Step 2: Document source-of-truth and catalog semantics**

Use this contract:

```text
Individual Markdown notes are source records. memory.db is derived. MEMORY.md is
excluded by default because catalogs commonly duplicate source notes. A project that
has not migrated unique catalog-only content may temporarily set "exclude_files": []
in its private config; migrate that content before restoring the default.
```

- [ ] **Step 3: Document measured retrieval selection**

Keep vector as the generic default. Explain that `retrieval_mode: "hybrid"` is appropriate only when the corpus's private benchmark demonstrates better hit/MRR results. Do not copy private benchmark queries or expected paths into the repository.

- [ ] **Step 4: Document launcher migration**

State clearly:

- fresh installs receive a stable launcher
- existing customized engines are never overwritten
- the migration gate requires backup, direct public-engine tests, private benchmark parity, and explicit approval
- `AGENT_RULES_HOME` supports a nonstandard checkout path

- [ ] **Step 5: Run privacy and documentation checks**

```sh
./check-privacy.sh
rg -n '/Users/|/home/|employer|company-internal' README.md docs tools/recall setup
python3 -m json.tool tools/recall/config.example.json > /dev/null
git diff --check
```

Expected: privacy guard passes; the bounded search finds no private path or employer detail introduced by this work.

- [ ] **Step 6: Commit only after explicit confirmation**

```sh
git add README.md docs/setup.md docs/memory-and-recall.md tools/recall/README.md
git commit -m "docs(recall): explain shared reader writer deployment"
```

---

### Task 7: Back up private configuration and prove real-CLI parity

**Files:**
- Read: `~/.recall/config.json`
- Read: `~/.recall/recall.py`
- Read: `~/.recall/bench_labels.json`
- Create outside Git: `~/.recall/config.json.bak.pre-upstream-<timestamp>`
- Create temporarily outside Git: `~/.recall/.parity.<random>/`

**Interfaces:**
- Old engine and new public engine query the same configured read-only database
- Private benchmark/query text never enters `/tmp`, Git, tool output, or the final report
- No runtime engine replacement occurs in this task

- [ ] **Step 1: Record private runtime checksums and status**

```sh
shasum -a 256 ~/.recall/recall.py ~/.recall/recall ~/.recall/config.json
python3 ~/.recall/recall.py stats
```

Expected: current runtime works and checksums are recorded in session evidence without printing config contents.

- [ ] **Step 2: Request approval for the exact private config mutation**

Present the intended private-only additions (`retrieval_mode`, temporary `exclude_files`, and current effective `embed_url`), backup destination pattern, validation commands, and rollback command. Stop until the user explicitly approves modifying `~/.recall/config.json`; approval to implement public repository tasks is not approval for this private-state mutation.

- [ ] **Step 3: Create and validate a timestamped byte-identical config backup**

Run as one shell block so the backup path remains available:

```sh
set -euo pipefail
stamp="$(date +%Y%m%d-%H%M%S)"
backup="$HOME/.recall/config.json.bak.pre-upstream-$stamp"
test ! -e "$backup"
cp -p "$HOME/.recall/config.json" "$backup"
cmp "$HOME/.recall/config.json" "$backup"
python3 -m json.tool "$backup" > /dev/null
printf '%s\n' "$backup" > "$HOME/.recall/.pre-upstream-config-backup-path"
chmod 600 "$backup" "$HOME/.recall/.pre-upstream-config-backup-path"
```

Expected: backup is byte-identical, parseable, mode-restricted, and its path is recorded outside Git.

- [ ] **Step 4: Apply compatibility fields atomically and validate**

Use the current engine's effective endpoint without printing it:

```sh
python3 - <<'PY'
import json
import os
from pathlib import Path
import runpy

home = Path.home()
path = home / ".recall" / "config.json"
config = json.loads(path.read_text(encoding="utf-8"))
old_engine = runpy.run_path(str(home / ".recall" / "recall.py"), run_name="pre_upstream_engine")
config["retrieval_mode"] = "hybrid"
config["exclude_files"] = []
config["embed_url"] = old_engine["EMBED_URL"]
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY
python3 -m json.tool ~/.recall/config.json > /dev/null
```

If validation fails, restore immediately:

```sh
backup="$(cat ~/.recall/.pre-upstream-config-backup-path)"
cp -p "$backup" ~/.recall/config.json
python3 -m json.tool ~/.recall/config.json > /dev/null
```

Never print or commit the config.

- [ ] **Step 5: Compare private benchmark metrics in a protected directory**

```sh
set -euo pipefail
PARITY_DIR="$(mktemp -d "$HOME/.recall/.parity.XXXXXX")"
chmod 700 "$PARITY_DIR"
trap 'rm -rf "$PARITY_DIR"' EXIT
(cd "$HOME/.recall" && python3 bench_quality.py --json > "$PARITY_DIR/before.json")
(cd "$HOME/.agent-rules/tools/recall" && python3 bench_quality.py --json > "$PARITY_DIR/after.json")
chmod 600 "$PARITY_DIR"/*.json
python3 -m json.tool "$PARITY_DIR/before.json" > /dev/null
python3 -m json.tool "$PARITY_DIR/after.json" > /dev/null
python3 - "$PARITY_DIR/before.json" "$PARITY_DIR/after.json" <<'PY'
import json
import sys
before = json.load(open(sys.argv[1], encoding="utf-8"))["results"]["hybrid"]
after = json.load(open(sys.argv[2], encoding="utf-8"))["results"]["hybrid"]
for metric in ("hit@1", "hit@3", "hit@5", "mrr"):
    if after[metric] < before[metric]:
        raise SystemExit(f"hybrid parity regression in {metric}")
print("private benchmark parity: PASS")
PY
```

Expected: only aggregate pass/fail leaves the protected directory. The trap deletes private query data.

- [ ] **Step 6: Exercise the actual old and canonical CLIs and compare ordered citations**

Within the same protected-directory pattern, run the first ten private labeled queries through both real CLI entrypoints. Store raw output mode 600, compare only parsed ordered citation lists, and print query indexes rather than query text on mismatch:

```python
import json
from pathlib import Path
import re
import subprocess
import sys

home = Path.home()
work = Path(sys.argv[1])
labels = json.loads((home / ".recall" / "bench_labels.json").read_text(encoding="utf-8"))[:10]
old_engine = home / ".recall" / "recall.py"
new_engine = home / ".agent-rules" / "tools" / "recall" / "recall.py"
header = re.compile(r"^\[[^]]+\]\s+(.+):([0-9]+)$")

def run(engine, query, index, lane):
    result = subprocess.run(
        [sys.executable, str(engine), query, "-k", "5", "--hybrid"],
        text=True, capture_output=True, check=True,
    )
    target = work / f"{lane}-{index}.txt"
    target.write_text(result.stdout, encoding="utf-8")
    target.chmod(0o600)
    return [match.group(1) for line in result.stdout.splitlines()
            if (match := header.match(line))]

mismatches = []
for index, (query, _) in enumerate(labels):
    if run(old_engine, query, index, "old") != run(new_engine, query, index, "new"):
        mismatches.append(index)
if mismatches:
    raise SystemExit(f"ordered CLI citation mismatch at private query indexes {mismatches}")
print(f"real CLI parity: PASS ({len(labels)} queries)")
```

Also run one known synthetic phrase through the canonical CLI and assert every result header matches `[tag] source/relative-path.md:line`; this explicitly covers configured mode selection, CLI flags, citation rendering, and pre/post-`rel` decoding rather than only ranking internals.

- [ ] **Step 7: Verify role and catalog compatibility**

```sh
python3 ~/.agent-rules/tools/recall/recall.py stats
if python3 ~/.agent-rules/tools/recall/recall.py index; then
  echo "FAIL: reader index unexpectedly succeeded" >&2
  exit 1
fi
```

Expected: `stats` reports reader role, hybrid retrieval mode, sanitized endpoint, and configured database; `index` refuses with exit 2. Because private `exclude_files` is temporarily empty, current `MEMORY.md` retrieval remains unchanged until its separate migration.

- [ ] **Step 8: Stop on any mismatch and restore config when abandoning migration**

Do not replace the runtime if the database path differs, role differs, metrics regress, ordered citations differ, pre-`rel` rows fail, `index` mutates the reader, or catalog-backed queries disappear. If migration is abandoned, restore the recorded config backup and validate it before deleting `.pre-upstream-config-backup-path`.

This task changes only the separately approved private config and produces no Git commit.

---

### Task 8: Upgrade and republish from the writer before reader migration

**Files:**
- On the configured writer only: `~/.recall/config.json`
- On the configured writer only: local agent-rules checkout and recall database
- Preserve: current published snapshot until atomic replacement succeeds

**Interfaces:**
- Writer runs the canonical engine directly before receiving the launcher
- Published snapshot must contain `chunks.rel`
- Readers are not migrated until they have observed and queried the republished snapshot

- [ ] **Step 1: Prove the target machine is the writer**

Run locally on the configured writer, not through an unapproved remote shell:

```sh
python3 ~/.recall/recall.py stats
```

Expected: `role=writer` and a publish destination is configured. Stop if role is reader or the publish destination is absent.

- [ ] **Step 2: Request exact writer-migration approval**

Present the writer config backup path, compatibility fields, canonical engine path, rebuild/publish command, expected source roots, current database checksum, current published-snapshot checksum, and rollback behavior. If reaching the writer requires SSH or another remote command, separately obtain explicit approval for that exact remote access and mutation.

- [ ] **Step 3: Back up and atomically extend writer config**

Repeat Task 7 Steps 3–4 on the writer: create a timestamped byte-identical mode-600 backup, validate both JSON files, add `retrieval_mode: "hybrid"`, temporary `exclude_files: []`, and the current effective `embed_url`, then record the backup path outside Git. Restore immediately on parse or smoke-test failure.

- [ ] **Step 4: Validate canonical engine against the current writer database without mutation**

```sh
python3 ~/.agent-rules/tools/recall/recall.py stats
```

Expected: writer role, correct database size, configured mode, and sanitized endpoint. Run one bounded query and verify source-relative citation output before rebuilding.

- [ ] **Step 5: Rebuild and atomically publish writer-first**

```sh
python3 ~/.agent-rules/tools/recall/recall.py index --rebuild --publish
```

Expected: source-root preflight succeeds, rebuild commits as one transaction, and the published snapshot changes only after successful completion. On interruption, the previous writer DB and published snapshot remain queryable.

- [ ] **Step 6: Verify schema and publication without printing private paths**

Run a local Python check that loads `db_path` and `publish_path` from private config, opens both through libSQL read-only URI mode, and asserts:

```python
columns = {row[1] for row in cursor.execute("PRAGMA table_info(chunks)").fetchall()}
assert "rel" in columns
assert cursor.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
```

Print only `writer schema/publication: PASS`, never configured paths or corpus content.

- [ ] **Step 7: Confirm a reader has received and queried the new snapshot**

Before replacing any reader runtime, run its existing engine:

```sh
python3 ~/.recall/recall.py stats
python3 ~/.recall/recall.py "writer first schema smoke test" -k 3
```

Expected: the reader opens the republished database and returns results. If synchronization has not delivered the new snapshot, stop and wait rather than migrating the launcher.

---

### Task 9: Migrate the private reader runtime behind an explicit owner gate

**Files:**
- Preserve: `~/.recall/recall.py.pre-upstream`
- Replace after approval: `~/.recall/recall.py`
- Preserve: every other `~/.recall` file

**Interfaces:**
- `~/.recall/recall.py` becomes the stable launcher
- canonical behavior comes from `~/.agent-rules/tools/recall/recall.py`

- [ ] **Step 1: Present the migration evidence and request explicit approval**

Report old engine checksum, public tests, synthetic real-libSQL smoke, private aggregate benchmark parity, real-CLI ordered-citation parity, reader refusal evidence, writer-first publication evidence, exact files affected, and rollback command. Obtain approval for this exact private runtime replacement.

- [ ] **Step 2: Make a recoverable backup**

```sh
test ! -e ~/.recall/recall.py.pre-upstream
cp -p ~/.recall/recall.py ~/.recall/recall.py.pre-upstream
cmp ~/.recall/recall.py ~/.recall/recall.py.pre-upstream
```

Expected: backup is byte-identical and the destination did not previously exist.

- [ ] **Step 3: Install the launcher without touching state**

```sh
cp -p ~/.agent-rules/tools/recall/launcher.py ~/.recall/recall.py
chmod +x ~/.recall/recall.py
```

Do not modify config, database, labels, or published snapshot.

- [ ] **Step 4: Verify the live path**

```sh
python3 ~/.recall/recall.py stats
python3 ~/.recall/recall.py "launcher migration smoke test" -k 3
```

Expected: role/database/mode match pre-migration state and results use source-relative citations.

- [ ] **Step 5: Prove rollback**

Do not execute rollback when verification passes. If any live verification fails, execute and verify:

```sh
cp -p ~/.recall/recall.py.pre-upstream ~/.recall/recall.py
python3 ~/.recall/recall.py stats
```

---

### Task 10: Run final repository verification and independent review

**Files:**
- Verify all modified public files
- Do not stage `workflows/wrap/SKILL.md`

**Interfaces:**
- Produces complete test and privacy evidence for the upstream change

- [ ] **Step 1: Run the full local verification suite**

```sh
cd ~/.agent-rules
python3 -m unittest discover -s tools/recall -p 'test_*.py' -v
bash setup/test-fresh-install.sh
bash setup/test-workflows.sh
bash setup/test-compaction-config.sh
./check-privacy.sh
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 2: Confirm foreign dirty work remains untouched**

```sh
git status --short
git diff -- workflows/wrap/SKILL.md
```

Expected: the pre-existing wrap modification remains present but is absent from the recall implementation's staged-file set.

- [ ] **Step 3: Review the exact upstream delta**

```sh
git diff --stat
git diff --name-status
git diff -- tools/recall setup docs README.md .github/workflows/ci.yml
```

Expected public files, plus this plan if it has not already received its separately approved commit:

```text
.github/workflows/ci.yml
docs/superpowers/plans/2026-08-29-recall-upstream.md
docs/memory-and-recall.md
docs/setup.md
README.md
setup/doctor.sh
setup/install.sh
setup/test-fresh-install.sh
tools/recall/README.md
tools/recall/bench_quality.py
tools/recall/config.example.json
tools/recall/launcher.py
tools/recall/recall.py
tools/recall/test_recall.py
```

- [ ] **Step 4: Request independent code review**

Reviewer must check:

- reader cannot mutate DB
- publish is atomic and quote-safe
- intake note is saved before optional indexing
- launcher cannot recursively load itself
- malformed config fails visibly
- catalog exclusion has a temporary migration override
- no private data entered the public tree
- old database rows with null `rel` still render

- [ ] **Step 5: Stop for commit/push decision**

Report verified status, exact diff, residual risks, private runtime migration result, and the untouched wrap diff. Do not commit or push until the user explicitly approves those named actions.

---

## Deferred Follow-Up Plans

This plan intentionally does not mix independent workstreams into the recall-engine change:

1. **Private catalog migration:** relocate or verify the seven non-linked `MEMORY.md` rules, remove the temporary private `exclude_files: []`, rebuild on the writer, publish, and verify reader retrieval.
2. **Hybrid wrap workflow:** preserve private adapter routing, enforce project-local-only generic writes, stop when corpus conventions are missing, avoid mandatory `MEMORY.md`, handle stale conflicts through maintenance, and add compacted-session tail recovery to the vault prompt.
3. **Privacy guard correctness:** distinguish grep/Git operational errors from clean scans and optionally require private patterns in strict release mode.
4. **Installer registry contract:** preflight all effective registries and propagate every `REFUSE` as a nonzero result.

Each follow-up should receive its own spec/plan and review gate because it changes a separate safety boundary.
