# Skill Registry Design

## Problem

The agent-rules hub owns reusable workflows under `workflows/`, but `setup/install.sh`
only projects instruction files. Skill discovery therefore depends on unrelated manual
symlinks, and a runtime can miss a hub workflow even when that workflow already exists.

## Goals

- Make hub-owned, generic workflows reproducibly discoverable by supported runtimes.
- Keep private and project-specific skill sources outside this public repository.
- Allow a private skill to override a generic hub workflow without publishing its path.
- Refuse to overwrite user-owned files or directories.
- Detect missing, broken, and incorrect registrations with `setup/doctor.sh`.

## Design

Add a public `workflow-map` beside `map`. Each non-comment line names a workflow,
its repository-relative source, and the runtime catalogs that should receive a
symlink. The initial entries cover the existing hub workflows.

An optional private registry at `${XDG_CONFIG_HOME:-$HOME/.config}/agent-rules/workflow-map`
uses the same format. Private entries are loaded after public entries and may replace
an entry with the same workflow name. This keeps personal paths and project-specific
choices out of the public repository while preserving reproducible local setup.

`setup/install.sh` will:

1. Parse and validate the public registry, then apply private overrides.
2. Resolve repository-relative public sources and home-relative private sources.
3. Create the required runtime catalog directories when absent.
4. Create or repair symlinks when the destination is absent or already a symlink.
5. Refuse to replace a real file or directory and report the conflict.
6. Avoid replacing a skill directory when that directory is itself the selected source.

`setup/doctor.sh` will resolve the same effective registry and verify that every
declared destination points to the selected source. It will report absent sources,
missing links, incorrect links, and non-symlink conflicts.

## Runtime targets

The registry supports the shared catalog and explicit runtime catalogs. Initial
targets are `agents`, `codex`, and `claude`, mapping respectively to
`~/.agents/skills`, `~/.codex/skills`, and `~/.claude/skills`. Explicit targets avoid
assuming that every runtime reads the shared catalog.

## Private `wrap` overlay

The public registry installs the generic hub `wrap`. A machine that needs the
personal unified wrapper can add a private `wrap` entry pointing at its existing
private skill directory. The installer then projects that source to the other
catalogs while leaving the source directory untouched.

## Verification

- Extend the fresh-install test to use a temporary home and assert all public links.
- Add cases for a private override, idempotent reinstall, and refusal to clobber a
  real destination.
- Run `setup/doctor.sh` against the temporary installation and the actual machine.

## Non-goals

- Copying every installed or third-party skill into the agent-rules repository.
- Publishing private skill content or machine-specific absolute paths.
- Choosing precedence between duplicate skill names inside a runtime itself.
