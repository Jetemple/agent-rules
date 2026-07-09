# Compaction (both agents)

Long sessions eventually fill the model's context window. **Auto-compaction** summarizes older
context into a compact form so work can continue without a hard stop. Enable it on both agents
and let the harness handle it rather than nagging yourself to `/compact`.

> The numbers below are **example values** for a 200k-token window. Pick your own based on the
> model window you actually run and how much headroom you want.

## Claude Code

Set in your settings JSON:

```json
{
  "autoCompactEnabled": true,
  "autoCompactWindow": 150000
}
```

The window math: `used tokens + free space + auto-compact buffer = model window`. With a 200k
window and `autoCompactWindow=150000`, you reserve ~50k as the compaction buffer, and
auto-compaction fires as free space approaches zero.

- `/context` is the **live source of truth** for the current session's actual trigger — check
  it if the buffer doesn't look right.
- A running session may not pick up a settings change; run `/compact` manually at the next safe
  turn boundary, and restart the session when convenient.

## Codex CLI

Set in `~/.codex/config.toml`:

```toml
model_auto_compact_token_limit = 150000
```

If you use them, PreCompact / PostCompact hooks (in `~/.codex/hooks.json`) can drop anchor notes
so key state survives the summary. Codex compaction is independent of Claude Code's setting —
watch Codex's own context status line and keep reads bounded.

## Manual compaction

Suggest a manual `/compact` only after substantial context growth: large command output,
CI/log/PR triage, broad codebase scouting, or before switching to a different task. When you do,
leave a short checkpoint capturing only state that must survive. After compaction, trust the
restored anchors and the newest request — don't re-read broad context you already paged through.
