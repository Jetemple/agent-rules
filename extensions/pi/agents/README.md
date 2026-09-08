# Pi agents extension

A bounded subagent extension for [Pi](https://github.com/earendil-works/pi). It adds:

- `delegate` / `/delegate` — run one isolated read-only scout, reviewer, or skeptic.
- `council` / `/council` — ask two to five configured models the same question and preserve disagreements for the parent agent to synthesize.

Child Pi processes start with normal extensions, skills, prompt templates, context files, and built-in tools disabled. `child-guard.ts` exposes only bounded `safe_read`, `safe_grep`, and `safe_find` tools; blocks sensitive paths and paths outside the selected working directory; caps file and output sizes; and rejects symlinks and hard-linked files.

## Install

`setup/install.sh` links this directory to `~/.pi/agent/extensions/agents`. Pi auto-discovers it there. Run `/reload` in an existing Pi session after installation.

The installer will not overwrite a real directory already at that path. Move or reconcile an existing local copy first.

## Model configuration

Without configuration, the five aliases use the defaults in `index.ts`. To override providers, model IDs, or provider extensions, copy the example:

```sh
mkdir -p ~/.config/agent-rules
cp setup/pi-agents.example.json ~/.config/agent-rules/pi-agents.json
$EDITOR ~/.config/agent-rules/pi-agents.json
```

Set `PI_AGENTS_CONFIG` to use another config path. Each model entry is optional and overrides only that alias. `extensions` contains trusted Pi extension paths that the otherwise isolated child must load—for example, a private extension that registers a custom provider. Use absolute paths or `~/...` paths.

Provider extensions run with full local permissions during child startup. Only list code you trust. Keep private endpoints, credentials, and organization-specific model IDs in the untracked local config, never in this public repo.

## Limits

- Child timeout: 5 minutes
- Council size: 2–5 models
- Council concurrency: 2
- Child output cap: 12 KiB each
- Council output cap: 48 KiB
- Child final response contract: under 120 lines
