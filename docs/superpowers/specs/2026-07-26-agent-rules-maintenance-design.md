# Agent Rules Maintenance Design

## Goal

Bring the local agent-rules hub up to date, align its compaction guidance with the
machine's 200k Claude and Codex configuration, repair detected installation drift,
and preserve machine-specific recall behavior.

## Scope

- Fast-forward the checkout by the two existing upstream commits.
- Preserve the uncommitted default-branch/release safety rule in `core.md`.
- Preserve the independently evolved `~/.recall/recall.py`; the public installer
  must continue treating it as a seed-once, device-local file.
- Change the public compaction example from 150k to 200k using Claude's documented
  environment-variable form.
- Add a short shared continuity rule describing the state that must survive
  compaction.
- Replace the duplicate Claude `handoff` directory with the registry-managed
  symlink, retaining a recoverable backup.
- Refresh managed instruction blocks and workflow registrations with the installer.
- Verify repository tests, privacy checks, installed wiring, and live recall.

## Design

The repo remains a generic public configuration hub. Machine-specific implementation
details stay outside it, while checked-in examples document supported public
configuration. A focused shell test owns the compaction-example contract so future
changes cannot silently return the docs and example config to different values or
different configuration shapes.

The continuity rule belongs in `core.md` because both Claude and Codex need the same
minimal handoff state: objective, decisions, changed files, verification evidence,
blockers, and next action. Raw logs and abandoned exploration are explicitly
discardable.

Installation repair is recoverable. The existing real `handoff` directory is moved
to a dated backup before the installer creates the declared symlink. The personalized
recall script is neither replaced nor normalized against the public copy.

## Verification

- Observe the compaction-contract test fail before changing docs/config.
- Run it again after the changes and require a pass.
- Run the fresh-install and workflow-registry test suites.
- Run the privacy guard.
- Run the installer in dry-run mode, then apply it.
- Run `setup/doctor.sh` and require no failures.
- Confirm the personalized recall script checksum is unchanged.
- Run a recall query and confirm semantic mode when the local embedder is available.

## Commit Boundary

No commit, push, merge, PR, or release action is included. Those require a separate,
explicit confirmation after the final diff and verification evidence are known.
