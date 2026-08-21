# Pi Prompt Templates Design

## Goal

Manage Pi-only slash-command prompt templates in agent-rules, beginning with the existing `/goal` template.

## Design

Add a `prompt-map` registry with one row per managed template:

```text
# name  source           targets
goal    prompts/goal.md  pi
```

The canonical `/goal` content moves to `prompts/goal.md`. The installer resolves the `pi` target to `~/.pi/agent/prompts` and links each registered template as `<name>.md`.

Prompt templates remain separate from `workflow-map`. Workflows are cross-runtime skills; prompt templates use runtime-specific invocation and interpolation syntax.

## Safety

The installer follows the repository's existing inspect-before-act behavior:

- Create the link when the destination is absent.
- Leave a correct symlink unchanged.
- Replace a real destination file only when it is byte-identical to the canonical source. This safely adopts the existing `/goal` file.
- Refuse to overwrite a differing real file.
- Skip Pi when its configuration directory is absent.

## Validation

Automated tests will verify:

- Every registry entry has an existing Markdown source.
- Unknown targets and malformed entries fail validation.
- A fresh install creates the Pi template link.
- Re-running the installer is idempotent.
- An identical real file is safely adopted.
- A differing real file is preserved and reported.
- The doctor detects missing, incorrect, or drifted prompt-template links.

The existing privacy check, shellcheck, workflow tests, and fresh-install tests must continue to pass.

## Scope

This change registers only `/goal`. It establishes the mechanism for future Pi templates without converting templates into cross-agent skills or changing `/goal` behavior.
