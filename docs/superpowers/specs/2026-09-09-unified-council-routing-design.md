# Unified Council Routing Design

**Date:** 2026-09-09
**Status:** Draft for review

## Goal

Provide one global `/council` command that works in every Pi project, selects the configured normal roster outside protected projects, selects privacy-safe routes inside protected projects, and rejects unsafe or ambiguous routing before any child prompt leaves the parent process.

## User Experience

Pi exposes one `/council` command from the global bounded-agents extension. Project prompt templates do not shadow that command. Council-maintenance skills use names that do not collide with `/council` autocomplete.

The user maintains one machine-local model catalog at `~/.config/agent-rules/pi-agents.json`. Adding a model means adding one honest model entry and, when desired, adding its name to the normal council default or a project policy's protected council override.

A normal project uses the global default roster. A protected project uses the nearest applicable project policy's council override. The command behaves the same way whether the protected location is the parent session working directory or a requested child working directory.

## Configuration Ownership

### Machine-local model catalog

`pi-agents.json` remains authoritative for:

- every model name and exact `provider` plus `id` route;
- trusted provider-extension paths;
- optional reviewer perspectives;
- delegate role defaults;
- the normal council roster used when no applicable project policy overrides it.

The file remains machine-local because direct accounts, private provider extensions, and route preferences do not belong in the public repository.

The separate `council.json` experiment is removed. Two independent user-level files created conflicting sources of truth and left one roster unused by the runtime.

### Project policy

`.pi/pi-agents-policy.json` keeps its exact route allowlist and gains an optional `council` array of configured model names:

```json
{
  "version": 1,
  "allowedModels": [
    { "provider": "example-zdr-provider", "id": "example-private-model" },
    { "provider": "example-subscription", "id": "example-accepted-model" }
  ],
  "council": ["private-reviewer", "accepted-reviewer"]
}
```

`allowedModels` is the security boundary. `council` only selects defaults and cannot authorize a route. Every selected name must resolve through `pi-agents.json`, and every resolved route must independently pass every applicable exact-route allowlist.

A policy may omit `council`; in that case it restricts routes without replacing the normal roster. If the normal roster contains a denied route, the launch fails closed. It does not silently filter or substitute members.

## Scoped Roster Resolution

The runtime canonicalizes both the parent session CWD and requested child CWD before policy discovery.

For each location, it finds the nearest applicable project policy. Canonically identical policy files are deduplicated.

Roster selection follows these rules:

1. An explicit `council.members` tool argument remains an explicit request and takes precedence over defaults.
2. Without explicit members, collect the optional `council` override from every applicable policy.
3. If no applicable policy supplies an override, use `pi-agents.json.defaults.council`.
4. If one unique override is supplied, use it.
5. If multiple applicable policies supply byte-for-byte identical member arrays, use that array.
6. If applicable policies supply different arrays, reject the launch before task construction, progress updates, or process creation.
7. Resolve every selected model name, validate roster size and uniqueness, and authorize every exact route before spawning the first child.

This preserves sensitive-parent protection when a child CWD points outside the project and protects a sensitive child project when the parent starts elsewhere.

## Runtime and Command Behavior

The global extension remains the sole dispatcher for `delegate` and `council`. Child isolation remains unchanged.

`/council <question>` sends a user message instructing the main model to invoke the `council` tool without a `members` argument and then synthesize disagreements and evidence. Omitting `members` is important: the runtime, not the main model, selects the applicable scoped default.

Direct tool callers may provide explicit members. Protected-project policy still validates their resolved routes, so an explicit argument cannot bypass privacy policy.

User-visible council calls and results show each configured name with its exact `provider/id` route. Scoped-default previews should say `configured scoped default` until execution resolves the applicable policies; they must not misleadingly display the normal roster inside a protected project.

## Privacy and Failure Behavior

- Policy compares exact `(provider, id)` tuples, never aliases.
- A malformed model catalog or applicable policy prevents launch.
- An unknown roster member prevents launch.
- A denied route prevents launch.
- Conflicting applicable roster overrides prevent launch.
- A denied council starts zero child processes.
- No automatic ZDR discovery or provider-marketing inference occurs.
- Outside protected projects, configured non-ZDR routes are permitted by design. Documentation must state that absence of a project policy is not a privacy guarantee.
- Sensitive projects must explicitly list every approved exact route, including any accepted retention exception.

## Command Deduplication

After the global command passes end-to-end verification:

1. Remove or rename project-local `council.md` prompt templates that duplicate `/council`.
2. Keep third-party package council prompts disabled where already configured.
3. Rename any maintenance skill whose command name starts with `council` to a non-conflicting name such as `model-roster-rank`; changing its directory is unnecessary because Pi permits the frontmatter name to differ.
4. Verify `pi.getCommands()` exposes exactly one command named `council` in both protected and ordinary projects.

Private project cleanup is a deployment action, not content for this public repository. Public tests use temporary generic projects and model routes.

## Testing

Pure Bun tests cover:

- strict parsing of optional project `council` arrays;
- normal default selection with no policy override;
- protected override selection from parent or child CWD;
- canonical path and symlink behavior;
- identical override deduplication;
- conflicting override rejection;
- unknown, duplicate, undersized, and oversized rosters;
- alias remapping to a denied exact route;
- malformed policy failure;
- explicit member precedence without policy bypass;
- full preflight before any spawn.

An extension integration seam records child-launch attempts and proves:

- a denied or conflicting council starts zero children;
- an approved scoped council launches exactly the protected roster;
- an ordinary project launches exactly the normal roster;
- `/council` asks for runtime-selected members rather than embedding a roster.

Runtime discovery tests use Pi RPC `get_commands` and assert exactly one `council` command after private deployment cleanup. Full verification includes the agents test suite, installer tests, workflow tests, privacy check, doctor, and `git diff --check`.

## Migration

1. Complete and verify the already-started dynamic model and exact-route policy wiring.
2. Extend project policy with optional scoped roster selection.
3. Remove `council-config.ts`, its tests, and `setup/council.example.json`.
4. Update public documentation and examples around `pi-agents.json` plus project policy.
5. Prepare machine-local model aliases for normal direct routes and protected privacy-safe routes.
6. Add the protected project's exact-route allowlist and scoped roster override.
7. Reload Pi and verify one command plus both routing modes.
8. Only then remove the duplicate project prompt and rename the maintenance skill.

Rollback restores the project prompt and prior machine-local files. It must not weaken the exact-route policy merely to recover command availability.

## Non-goals

- Automatic privacy classification of arbitrary repositories.
- Automatic ZDR verification from provider APIs or marketing claims.
- Silent fallback from denied direct routes to similarly named privacy-safe routes.
- Dynamic per-question voting, judge weighting, or debate orchestration.
- Changes to child tool isolation, concurrency, output limits, or cancellation behavior.
