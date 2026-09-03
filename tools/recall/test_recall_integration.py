"""Real-libSQL integration test for the recall engine.

Drives the actual `recall.py` through subprocess calls against a throwaway
`$HOME`, a synthetic markdown corpus, and a loopback embedding server that
returns deterministic 768-element vectors. It never touches `~/.recall`, the
private label files, or the live database.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "recall.py"
DIM = 768
_STOP = {"task", "search", "result", "query", "title", "none", "text"}

try:  # the integration test needs the real driver; unit tests do not
    import libsql  # noqa: F401
    HAVE_LIBSQL = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_LIBSQL = False


def _vector(text):
    vec = [0.0] * DIM
    for raw in text.lower().split():
        tok = "".join(c for c in raw if c.isalnum())
        if len(tok) <= 2 or tok in _STOP:
            continue
        idx = int(hashlib.sha1(tok.encode()).hexdigest(), 16) % DIM
        vec[idx] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


class _EmbedHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        if self.server.fail:
            # 4xx is treated as permanent by the engine: fail fast, no retry
            # backoff, so the test stays quick.
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"forced failure")
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        vec = _vector(payload.get("input", ""))
        body = json.dumps({"data": [{"embedding": vec}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(HAVE_LIBSQL, "libsql driver not installed")
class RecallIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.corpus = self.home / "notes"
        (self.corpus / "alpha").mkdir(parents=True)
        (self.corpus / "beta").mkdir(parents=True)
        (self.corpus / "alpha" / "topic.md").write_text(
            "# Topic\n\nThe quantumsprocket calibration procedure lives here.\n",
            encoding="utf-8")
        (self.corpus / "beta" / "other.md").write_text(
            "# Other\n\nNotes about the flangewidget tolerance stack.\n",
            encoding="utf-8")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _EmbedHandler)
        self.server.fail = False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        port = self.server.server_address[1]
        self.endpoint = f"http://127.0.0.1:{port}/v1/embeddings"

        self.db = self.home / ".recall" / "memory.db"
        self.publish = self.home / "sync" / "published.db"
        (self.home / ".recall").mkdir(exist_ok=True)
        (self.home / ".config").mkdir(exist_ok=True)
        self._write_config()

    def _write_config(self, sources=None):
        cfg = {
            "sources": sources if sources is not None
            else [{"label": "notes", "path": str(self.corpus)}],
            "db_path": str(self.db),
            "publish_path": str(self.publish),
            "read_only": False,
            "inbox": str(self.corpus / "_inbox"),
            "retrieval_mode": "hybrid",
            "embed_url": self.endpoint,
            "embed_model": "test-model",
        }
        (self.home / ".recall" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def run_cli(self, *args, check=True):
        env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "PATH": os.environ.get("PATH", ""),
        }
        proc = subprocess.run(
            [sys.executable, str(ENGINE), *args],
            capture_output=True, text=True, env=env)
        if check:
            self.assertEqual(proc.returncode, 0,
                             msg=f"{args} failed:\n{proc.stdout}\n{proc.stderr}")
        return proc

    def test_end_to_end(self):
        # 1. index --publish builds the DB and the snapshot
        self.run_cli("index", "--publish")
        self.assertTrue(self.db.exists())
        self.assertTrue(self.publish.exists())
        first_ino = self.publish.stat().st_ino

        # 2. an unchanged index --publish does not replace the snapshot
        self.run_cli("index", "--publish")
        self.assertEqual(self.publish.stat().st_ino, first_ino)

        # 3. add --title --publish writes only inside the scratch inbox and
        #    refreshes the snapshot
        before = set(p.name for p in (self.corpus / "_inbox").glob("*.md")) \
            if (self.corpus / "_inbox").exists() else set()
        add = self.run_cli("add", "--title", "Synthetic title", "--publish",
                           "synthetic durable quantumsprocket fact")
        created = Path(add.stdout.strip().splitlines()[-1])
        self.assertTrue(str(created).startswith(str(self.home)))
        self.assertEqual(created.parent, self.corpus / "_inbox")
        after = set(p.name for p in (self.corpus / "_inbox").glob("*.md"))
        self.assertEqual(len(after - before), 1)
        self.assertNotEqual(self.publish.stat().st_ino, first_ino)

        # 4. hybrid query returns the expected source-relative citation
        hy = self.run_cli("quantumsprocket calibration")
        self.assertIn("notes/alpha/topic.md:", hy.stdout)

        # 5. --vector executes and also reports a source-relative citation
        ve = self.run_cli("flangewidget tolerance", "--vector")
        self.assertIn("notes/beta/other.md:", ve.stdout)

        # 6. stats reports role, configured mode, and the sanitized loopback host
        st = self.run_cli("stats")
        self.assertIn("role=writer", st.stdout)
        self.assertIn("retrieval_mode=hybrid", st.stdout)
        self.assertIn(f"embedder=http://127.0.0.1:{self.server.server_address[1]}/v1/embeddings",
                      st.stdout)

        # 7. a forced embedder failure during index --rebuild leaves the prior
        #    DB queryable (keyword-only)
        self.server.fail = True
        failed = self.run_cli("index", "--rebuild", check=False)
        self.assertNotEqual(failed.returncode, 0)
        degraded = self.run_cli("quantumsprocket")
        self.assertIn("notes/alpha/topic.md:", degraded.stdout)
        self.server.fail = False

        # 8. a missing source root exits 2 without deleting indexed rows
        self._write_config(sources=[{"label": "notes", "path": str(self.home / "gone")}])
        missing = self.run_cli("index", check=False)
        self.assertEqual(missing.returncode, 2)
        self._write_config()
        still = self.run_cli("quantumsprocket")
        self.assertIn("notes/alpha/topic.md:", still.stdout)

    def test_incremental_index_backfills_and_publishes_portable_paths(self):
        self.run_cli("index")
        connection = libsql.connect(str(self.db))
        connection.execute("UPDATE chunks SET rel=NULL")
        connection.commit()
        connection.close()

        # An unchanged corpus must upgrade path metadata without contacting the
        # embedder, and must count that upgrade so --publish refreshes readers.
        self.server.fail = True
        self.run_cli("index", "--publish")
        for database in (self.db, self.publish):
            connection = libsql.connect(str(database))
            missing = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE rel IS NULL").fetchone()[0]
            connection.close()
            self.assertEqual(missing, 0)

    def test_deletion_only_index_refreshes_published_snapshot(self):
        self.run_cli("index", "--publish")
        deleted = self.corpus / "beta" / "other.md"
        deleted.unlink()

        self.run_cli("index", "--publish")

        connection = libsql.connect(str(self.publish))
        remaining = connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE path=?", (str(deleted),)).fetchone()[0]
        connection.close()
        self.assertEqual(remaining, 0)

    def test_index_publish_retries_when_writer_db_is_ahead(self):
        self.run_cli("index", "--publish")
        note = self.corpus / "alpha" / "topic.md"
        note.write_text("# Topic\n\nNew retryable snapshot content.\n", encoding="utf-8")

        # This models a successful index followed by a failed publish. The retry
        # sees no corpus changes, but the writer DB is newer than the snapshot.
        self.run_cli("index")
        retry = self.run_cli("index", "--publish")
        self.assertIn("published snapshot", retry.stderr)

        connection = libsql.connect(str(self.publish))
        text = connection.execute(
            "SELECT txt FROM chunks WHERE path=?", (str(note),)).fetchone()[0]
        connection.close()
        self.assertIn("New retryable snapshot content", text)


if __name__ == "__main__":
    unittest.main()
