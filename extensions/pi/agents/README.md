# Pi agents extension

A bounded subagent extension for [Pi](https://github.com/earendil-works/pi). It adds:

- `delegate` / `/delegate` for one isolated read-only scout, reviewer, or skeptic.
- `council` / `/council` for two to five configured models to review the same question while preserving disagreements for the parent agent to synthesize.

Child Pi processes start with normal extensions, skills, prompt templates, context files, and built-in tools disabled. `child-guard.ts` exposes only bounded `safe_read`, `safe_grep`, and `safe_find` tools; blocks sensitive paths and paths outside the selected working directory; caps file and output sizes; and rejects symlinks and hard-linked files.

## Install

`setup/install.sh` links this directory to `~/.pi/agent/extensions/agents`. Pi auto-discovers it there. Run `/reload` in an existing Pi session after installation.

The installer will not overwrite a real directory already at that path. Move or reconcile an existing local copy first.

## Machine-local model catalog

The extension uses safe public defaults when `~/.config/agent-rules/pi-agents.json` is absent. When the file is present, it is authoritative: it must contain the complete model catalog and defaults, and hidden built-in aliases are not merged into it.

To configure model routes, copy the generic example and replace its values locally:

```sh
mkdir -p ~/.config/agent-rules
cp setup/pi-agents.example.json ~/.config/agent-rules/pi-agents.json
$EDITOR ~/.config/agent-rules/pi-agents.json
```

Each model key is the exact name accepted by `delegate.model` and `council.members`. A model entry contains an exact `provider` and `id`, optional trusted Pi `extensions` paths, and an optional council `perspective`. Defaults for `scout`, `reviewer`, `skeptic`, and `council` must reference configured names. The council default must contain two to five unique names. Set `PI_AGENTS_CONFIG` to use another catalog path.

Provider extensions run with full local permissions during child startup. Only list code you trust. Keep private endpoints, credentials, provider extensions, and organization-specific model IDs in the untracked local config, never in this public repository.

Changing the catalog changes the tool schemas at extension load. Run `/reload` or start a fresh Pi session after editing it.

## Project route policy

A project can restrict exact routes with `.pi/pi-agents-policy.json`:

```json
{
  "version": 1,
  "allowedModels": [
    { "provider": "example-provider", "id": "example-approved-model" }
  ],
  "council": ["careful", "fast"]
}
```

Copy `setup/pi-agents-policy.example.json` into a project only after replacing its generic route with an approved local route. `allowedModels` is the security boundary. The optional `council` array only selects the scoped default and cannot authorize a route. Every selected name must resolve through `pi-agents.json`, and its resolved provider/ID tuple must pass every applicable allowlist.

Before a child starts, the extension canonicalizes both the parent session CWD and requested child CWD. It finds the nearest policy for each, deduplicates the same canonical policy file, and intersects all applicable policies. This prevents escaping a protected parent through another child CWD and prevents entering a protected child project from outside. Parent and child policies with different council arrays fail closed. Arrays are order-sensitive, and each contains two to five unique valid model names.

Explicit `council.members` bypasses scoped default selection but never bypasses route authorization. Unknown names, duplicate or incorrectly sized rosters, denied routes, conflicting scoped defaults, malformed JSON, and malformed existing policies reject the launch before progress or child creation. A project without a policy retains global behavior; absence of a policy is not a privacy guarantee. Sensitive projects must explicitly allow every approved exact route, including any accepted retention exception.

Calls and results display the configured name together with its exact `provider/id` route. Omitted council members display as a configured scoped default until the applicable project policies are resolved.

## Limits

- Child timeout: 5 minutes
- Council size: 2–5 models
- Council concurrency: 2
- Child output cap: 12 KiB each
- Council output cap: 48 KiB
- Child final response contract: under 120 lines
