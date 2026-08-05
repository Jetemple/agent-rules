# Codex custom model providers

How to add a non-OpenAI provider (DeepSeek as the worked example) to the Codex CLI without
breaking the OpenAI models. Verified against codex 0.146, 2026-08.

## One provider per session

`model_provider` in `~/.codex/config.toml` routes **every** model name to that provider's API.
Setting it globally to a custom provider silently breaks the OpenAI models — requests fail with
the provider's "unsupported model" error. Never flip the global default.

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
  that speak the Responses API work (as of 2026-08 that is `deepseek-v4-flash`;
  `deepseek-v4-pro` does not).
- The API key is read from the environment variable named by `env_key`. Export it from your
  shell profile; keep the key itself out of any synced or public file.

**TOML footgun:** every key after a `[table]` header until the next header belongs to that
table. Top-level settings (`sandbox_mode`, `approval_policy`, `model_verbosity`,
`model_auto_compact_token_limit`, ...) must appear **above** the first `[model_providers.*]`
header, or they are silently swallowed into the provider table and stop applying.

## Profiles: run both providers side by side

Keep the base config on OpenAI and create a standalone profile file
`$CODEX_HOME/<name>.config.toml` (e.g. `~/.codex/deepseek.config.toml`) that flips only the
model and provider:

```toml
model = "deepseek-v4-flash"
model_provider = "deepseek"
model_reasoning_effort = "high"
model_catalog_json = "~/.codex/model_catalog.json"
```

Launch with `codex --profile deepseek`. In this codex version, inline `[profiles.<name>]`
tables inside `config.toml` are **rejected** — profiles must be standalone files. Profile files
layer on top of the base config, which is why the provider definition above can live in the
base config only.

## Model catalog (the `/models` picker)

The picker is fed by the model catalog: point `model_catalog_json` at a JSON file with
`{"models": [...]}` entries shaped like codex's `ModelInfo`. Easiest path: copy an existing
entry from `~/.codex/models_cache.json` and override the fields. Gotchas:

- `default_reasoning_summary` is a string enum (`"auto"`), not null.
- `apply_patch_tool_type` only accepts `freeform`.
- `web_search_tool_type` only accepts `text` / `text_and_image`.

## Resume clobber

`codex resume` restores the session's pinned model and can write it back into `config.toml`,
clobbering your edits. Override per-resume with `codex resume --last -m <model>` or `/model`
in-TUI.
