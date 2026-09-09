# Pi Agents Dynamic Models and Project Policy Design

**Date:** 2026-09-08
**Status:** Approved direction

## Goal

Make the bounded Pi agents extension the single delegation runtime, with honest configurable model names and fail-closed route restrictions for sensitive projects.

## Decisions

### One dispatcher

The in-repo extension at `extensions/pi/agents/` owns `delegate` and `council`. It does not depend on third-party orchestration packages or profile catalogs. Child isolation remains unchanged: no inherited extensions, skills, prompt templates, context files, sessions, or normal tools; only the audited child guard is loaded.

### Dynamic model catalog

`~/.config/agent-rules/pi-agents.json` defines the complete model catalog when present. Model names are runtime keys such as `sol`, `grok`, `glm`, `deepseek`, or `muse`, not hardcoded aliases pretending to be another model.

Each model entry contains an exact `provider`, `id`, optional trusted provider-extension paths, and an optional council perspective. The same file defines defaults for each delegate role and the default council roster. Every referenced model must exist. Invalid configuration prevents the extension from loading rather than silently falling back.

When the file is absent, the public built-in catalog and defaults remain usable.

### Exact route identity

Security policy compares the resolved `(provider, id)` tuple, never an alias. Renaming or remapping an alias cannot bypass policy. User-visible calls, progress, and results display both the configured model name and exact `provider/id` route.

### Project policy

A project may define `.pi/pi-agents-policy.json`:

```json
{
  "version": 1,
  "allowedModels": [
    { "provider": "openrouter", "id": "example/model" }
  ]
}
```

Before spawning, the extension canonicalizes the parent session CWD and requested child CWD. It discovers the nearest policy governing each location. If either location has a policy, the selected route must be allowed by every applicable policy. This prevents escaping a sensitive parent project by requesting another child CWD and prevents entering a protected child project from outside.

An existing but malformed policy denies all delegation and reports the policy basename plus validation error. It never degrades to unrestricted execution. A project without a policy retains global behavior.

### Sensitive-project deployment

The project owner creates a local policy containing only routes approved for that repository. Non-approved and non-retention-safe models remain available globally but are denied in the protected project, including aliases that point to a familiar model name through another provider. Other privacy extensions remain defense in depth, but enforcement happens in the parent agents extension before any child prompt is transmitted. Device-specific route choices stay outside this public repository.

## Failure behavior

- Unknown model name: reject before spawn and list configured names.
- Missing default model: configuration-load failure.
- Duplicate or undersized council roster: configuration-load failure.
- Invalid provider-extension path type: configuration-load failure.
- Invalid project policy: reject all affected launches.
- Route denied by policy: reject before spawn and name the model plus exact route.
- Multiple applicable policies: require the route to satisfy their intersection.

## Testing

Pure configuration and policy modules receive Bun tests with temporary homes and project trees. Runtime tests inject a fake child launcher to prove denied routes never call spawn and approved routes pass the exact resolved model. Existing fresh-install tests continue to verify extension linkage and gain checks for the example configuration and project-policy example. CI runs the new Bun tests in a dedicated job.

## Non-goals

- General workflow algebra, mutable worker agents, resumable sessions, or background missions.
- Automatic ZDR discovery from provider marketing or account state.
- Loading Recall inside children.
- Silently migrating old alias-based configuration.
- Automatically adding non-ZDR models to a sensitive-project allowlist.
