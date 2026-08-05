# Codex custom model providers

Add a non-OpenAI provider (DeepSeek as the worked example) to the Codex CLI without breaking
the OpenAI models. Verified against codex 0.146, 2026-08.

## One provider per session

`model_provider` in `~/.codex/config.toml` routes **every** model name to that provider's API —
setting it globally to a custom provider silently breaks the OpenAI models ("unsupported
model" errors). Never flip the global default; use a profile (below).

## Provider definition (base config)

Declare the provider in the base `~/.codex/config.toml` so profiles can reference it:

```toml
[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com"
env_key = "DEEPSEEK_API_KEY"
wire_api = "responses"
```

- `wire_api = "responses"` is required — codex 0.146 dropped `wire_api = "chat"`. Only models
  speaking the Responses API work (as of 2026-08: `deepseek-v4-flash`; `deepseek-v4-pro` does
  not).
- The API key comes from the env var named by `env_key` — export it from your shell profile,
  never a synced or public file.

**TOML footgun:** every key after a `[table]` header belongs to that table until the next
header. Top-level settings (`sandbox_mode`, `approval_policy`, ...) must appear **above** the
first `[model_providers.*]` header, or they are silently swallowed and stop applying.

## Profiles: run both providers side by side

Keep the base config on OpenAI; create a standalone profile file
`$CODEX_HOME/<name>.config.toml` (e.g. `~/.codex/deepseek.config.toml`) that flips only:

```toml
model = "deepseek-v4-flash"
model_provider = "deepseek"
model_reasoning_effort = "high"
model_catalog_json = "~/.codex/model_catalog.json"
```

Launch with `codex --profile deepseek`. Inline `[profiles.<name>]` tables inside `config.toml`
are **rejected** in this version — profiles must be standalone files layered on the base
config (which is why the provider definition lives in the base).

## Model catalog (the `/models` picker)

Point `model_catalog_json` at a JSON file of `{"models": [...]}` entries shaped like codex's
`ModelInfo` — easiest is copying an entry from `~/.codex/models_cache.json` and overriding.
Gotchas: `default_reasoning_summary` is a string enum (`"auto"`), not null;
`apply_patch_tool_type` only accepts `freeform`; `web_search_tool_type` only accepts `text` /
`text_and_image`.

## Resume clobber

`codex resume` restores the session's pinned model and can write it back into `config.toml`,
clobbering your edits. Override per-resume with `codex resume --last -m <model>` or `/model`
in-TUI.
