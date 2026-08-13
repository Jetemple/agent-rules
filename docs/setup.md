# Setup (macOS / zsh)

Follow in order. An LLM on a fresh machine should be able to execute this top to bottom.

## 1. Prerequisites
1. **Homebrew** — https://brew.sh
2. **Python 3.13** — `brew install python@3.13`. (Do NOT use 3.14: it lacks a prebuilt
   `libsql` wheel that `tools/recall` needs.)
3. **llama.cpp** — `curl -LsSf https://llama.app/install.sh | sh` (official ggml-org
   installer; or `brew install llama.cpp`), then
   `llama download -hf ggml-org/embeddinggemma-300M-GGUF:Q8_0` and start the router
   server: `llama serve --models-preset ~/.config/llama.cpp/presets.ini`, with this
   minimal preset:

   ```ini
   version = 1

   [ggml-org/embeddinggemma-300M-GGUF:Q8_0]
   embeddings = true
   load-on-startup = true
   c = 2048
   b = 2048
   ub = 2048
   ```

   (`ub = 2048` matters: indexing embeds chunks longer than the 512-token default batch.)

   **Migrating an existing index from another embedder** (e.g. Ollama): document vectors
   embedded by a different runtime/quant live in a subtly different space than new query
   vectors — recall silently degrades instead of erroring. After switching, run
   `recall.py index --rebuild` on the machine that owns the DB (in shared-memory mode
   that is the writer, which then republishes; readers just pick up the new snapshot).

## 2. Clone + install
Clone into a dot folder in your home directory (e.g. `~/.agent-rules`), not a project/code
folder — every tool's global load-point points back at this checkout, so it should live
somewhere stable and out of the way.

```sh
git clone git@github.com:Jetemple/agent-rules.git ~/.agent-rules && cd ~/.agent-rules
# no SSH key? use HTTPS: git clone https://github.com/Jetemple/agent-rules.git
./setup/install.sh --dry-run   # preview every action
./setup/install.sh             # create the home-level symlinks
```

`install.sh` is idempotent and refuses to overwrite a real (non-symlink) file. It does four
things:

1. Reads `map` and symlinks each *installed* tool's global load-point at the hub file
   (e.g. `~/.codex/AGENTS.md` → `core.md`). Tools without a config dir are skipped.
2. Special-cases Claude: creates a core-only `~/.claude/AGENTS.md` stub (with an
   `@…/core.md` import line) if absent, and links `~/.claude/CLAUDE.md` → `AGENTS.md`. An
   existing personal file is never touched.
3. Installs the privacy-guard pre-commit hook.
4. Creates a stub `~/.config/agent-rules/private-patterns` if absent — **edit it**: add your
   name, handles, and employer as regexes so `check-privacy.sh` blocks them from ever being
   committed. It lives outside the repo so the guard never encodes your identity.

## 3. recall corpus bootstrap
`install.sh` seeds `~/.recall/recall.py` and friends once (a `copy_once` step). Build the
venv there, not inside the repo checkout:

```sh
cd ~/.recall
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # installs libsql
cp config.example.json config.json      # then edit the paths
python3 recall.py index                 # embeds the corpus into ~/.recall/memory.db
python3 recall.py "a test query"        # confirm you get ranked hits, not "(no matches)"
```

The example config points at `~/notes/memory` and `~/notes/vault` — edit to your real corpus
dirs, or `mkdir -p ~/notes/memory` to start empty. The index does **not** auto-build on first
query.

Repo updates to `tools/recall/recall.py` do **not** propagate automatically — `~/.recall` is
seeded once and left free to diverge per-device (same contract as `~/.claude/statusline.sh`).
Re-copy by hand if you want a repo-side fix. `~/.recall/memory.db` is a derived index — never
commit it.

## 4. Verify
```sh
./setup/doctor.sh                # phase-1 spine + (once recall is set) full checks
```

## 5. Commit-identity policy (public repo)
Before committing to this repo, ensure git identity carries NO employer email and NO real
name:
```sh
git config user.name "Jetemple"
git config user.email "<public no-employer email>"
```
