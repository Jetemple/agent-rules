#!/usr/bin/env python3
"""Stable launcher for the canonical recall engine.

Seeded once to ~/.recall/recall.py by setup/install.sh. It never contains
retrieval logic: it locates the canonical engine (tools/recall/recall.py in the
agent-rules checkout), re-execs under the device-local virtualenv when present,
and hands off. Importing it (e.g. from an installed benchmark) exports the
engine's namespace without running the CLI.
"""
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
