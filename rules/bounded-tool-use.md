# Rule: bounded tool use

Treat context as a limited budget. Prefer scoped, deterministic tools over broad ones that dump
large output into the session.

- Use `rg` (ripgrep) and narrow file reads before slower or broader alternatives.
- Prefer bounded local CLIs and small source slices before broad REST/API calls, full diffs,
  full logs, or whole-file dumps.
- When you must run a broad command, pipe it through a filter (`rg`, `--stat`, `head`, a line
  range) so only the relevant slice reaches the session.
- Read a directory or file only as far as the task needs. Don't re-read what you already have.
- For large scouting, high-risk review, or cross-file mapping, delegate to a bounded subagent
  with an explicit objective, scope, output contract, and stop condition — then work from its
  summary rather than re-reading everything it covered.

The goal: keep the working context small enough to reason about, so edits stay reliable and the
session lasts.
