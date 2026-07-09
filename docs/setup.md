# Setup (macOS / zsh)

Follow in order. An LLM on a fresh machine should be able to execute this top to bottom.

## 1. Prerequisites
1. **Homebrew** — https://brew.sh
2. **Python 3.13** — `brew install python@3.13`. (Do NOT use 3.14: it lacks a prebuilt
   `libsql` wheel that `tools/recall` needs.)
3. **Ollama** — `brew install ollama`, start the server (`brew services start ollama`, or
   `ollama serve` in a spare terminal), then `ollama pull embeddinggemma:300m`.

## 2. Clone + install
```sh
git clone git@github.com:Jetemple/agent-rules.git && cd agent-rules
# no SSH key? use HTTPS: git clone https://github.com/Jetemple/agent-rules.git
./setup/install.sh --dry-run   # preview every action
./setup/install.sh             # create the home-level symlinks
```
`install.sh` is idempotent and refuses to overwrite a real (non-symlink) file — see the
script header for its safety contract.

## 3. recall corpus bootstrap
`tools/recall` needs a local venv, a config, and a corpus — none of which are shipped.

```sh
cd tools/recall
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # installs libsql
```

Config is read from `~/.recall/config.json` (NOT the repo dir — the code looks in `~/.recall`):
```sh
mkdir -p ~/.recall
cp config.example.json ~/.recall/config.json    # then edit the paths
```
The example points at `~/notes/memory` and `~/notes/vault`. Edit those to your real corpus
dirs, or create them (`mkdir -p ~/notes/memory`) if you're starting empty.

Build the index once — it does **not** auto-build on first query:
```sh
python3 recall.py index          # embeds the corpus into ~/.recall/memory.db
python3 recall.py "a test query" # confirm you get ranked hits, not "(no matches)"
```
`~/.recall/memory.db` is a derived index (incremental on re-runs) — never commit it.

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
