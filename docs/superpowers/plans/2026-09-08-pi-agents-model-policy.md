# Pi Agents Dynamic Models and Project Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace misleading hardcoded model aliases with an honest dynamic catalog and deny unapproved model routes before delegated prompts leave sensitive projects.

**Architecture:** Split configuration and project-policy decisions out of the large Pi extension entrypoint into pure, independently tested modules. The entrypoint builds its tool schemas from the loaded catalog, preflights every resolved route against policies governing both parent and child working directories, and only then invokes the existing bounded child runner.

**Tech Stack:** TypeScript, Bun test, Pi extension API, TypeBox, Node filesystem/path APIs, Bash installer tests, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-08-pi-agents-model-policy-design.md`

## Global Constraints

- Keep `extensions/pi/agents/child-guard.ts` read-only and preserve its existing path, credential, symlink, hardlink, size, and output protections.
- Child Pi processes must continue using `--no-session`, `--no-extensions`, `--no-skills`, `--no-prompt-templates`, and `--no-context-files`.
- Compare project policy against the resolved `(provider, id)` tuple, never the configured model name.
- Apply every policy governing either the parent session CWD or requested child CWD; multiple policies intersect.
- An existing malformed policy denies launch before `spawn()` and never degrades to unrestricted execution.
- Keep device-specific providers, model IDs, paths, and project policies out of this public repository.
- Use TDD: observe each new regression test fail before production changes.
- Before every commit, stop and obtain the repository owner’s explicit approval for that exact commit and diff.

---

### Task 1: Extract and validate a dynamic model catalog

**Files:**
- Create: `extensions/pi/agents/config.ts`
- Create: `extensions/pi/agents/config.test.ts`
- Modify: `extensions/pi/agents/index.ts:13-75`

**Interfaces:**
- Produces: `ModelDefinition`, `AgentsConfig`, `DEFAULT_AGENTS_CONFIG`, `defaultConfigPath()`, and `loadAgentsConfig()`.
- `loadAgentsConfig(options?: { configPath?: string; home?: string; xdgConfigHome?: string }): AgentsConfig` returns a fully validated, immutable configuration.
- `AgentsConfig` has `models: Record<string, ModelDefinition>` and `defaults: { scout: string; reviewer: string; skeptic: string; council: string[] }`.
- A present config file is authoritative. It does not merge hidden built-in aliases into the configured catalog.

- [ ] **Step 1: Write failing configuration tests**

Create `extensions/pi/agents/config.test.ts` with temporary-directory cleanup and literal expectations:

```ts
import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  DEFAULT_AGENTS_CONFIG,
  loadAgentsConfig,
} from "./config.js";

const roots: string[] = [];
function tempRoot(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agents-config-"));
  roots.push(root);
  return root;
}
afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

function writeConfig(root: string, value: unknown): string {
  const file = path.join(root, "pi-agents.json");
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
  return file;
}

describe("loadAgentsConfig", () => {
  test("uses public defaults only when the config file is absent", () => {
    const root = tempRoot();
    expect(loadAgentsConfig({ configPath: path.join(root, "missing.json") })).toEqual(
      DEFAULT_AGENTS_CONFIG,
    );
  });

  test("uses configured names as the complete model catalog", () => {
    const file = writeConfig(tempRoot(), {
      models: {
        fast: { provider: "provider-a", id: "model-fast" },
        careful: {
          provider: "provider-b",
          id: "org/model-careful",
          perspective: "Challenge the leading assumption.",
        },
      },
      defaults: {
        scout: "fast",
        reviewer: "careful",
        skeptic: "careful",
        council: ["fast", "careful"],
      },
    });
    const config = loadAgentsConfig({ configPath: file });
    expect(Object.keys(config.models)).toEqual(["fast", "careful"]);
    expect(config.models.careful).toEqual({
      provider: "provider-b",
      id: "org/model-careful",
      perspective: "Challenge the leading assumption.",
    });
    expect(config.defaults.council).toEqual(["fast", "careful"]);
  });

  test.each([
    [{ models: {}, defaults: {} }, "at least one model"],
    [
      {
        models: { good: { provider: "p", id: "m" } },
        defaults: { scout: "missing", reviewer: "good", skeptic: "good", council: ["good", "missing"] },
      },
      "unknown model 'missing'",
    ],
    [
      {
        models: { good: { provider: "p", id: "m", extensions: "bad" } },
        defaults: { scout: "good", reviewer: "good", skeptic: "good", council: ["good", "good"] },
      },
      "extensions must be an array",
    ],
    [
      {
        models: { "Bad Name": { provider: "p", id: "m" } },
        defaults: { scout: "Bad Name", reviewer: "Bad Name", skeptic: "Bad Name", council: ["Bad Name"] },
      },
      "invalid model name",
    ],
  ])("rejects invalid configuration %#", (value, message) => {
    const file = writeConfig(tempRoot(), value);
    expect(() => loadAgentsConfig({ configPath: file })).toThrow(message);
  });
});
```

Add separate literal cases for unknown top-level keys, unknown model keys, empty provider/ID, duplicate council members, council sizes below 2 and above 5, missing defaults, and non-string `perspective` values.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
bun test extensions/pi/agents/config.test.ts
```

Expected: FAIL because `config.ts` does not exist.

- [ ] **Step 3: Implement the pure configuration module**

Create `extensions/pi/agents/config.ts` without Pi or TypeBox imports:

```ts
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export type ModelDefinition = {
  provider: string;
  id: string;
  extensions?: string[];
  perspective?: string;
};

export type AgentsConfig = {
  models: Readonly<Record<string, Readonly<ModelDefinition>>>;
  defaults: Readonly<{
    scout: string;
    reviewer: string;
    skeptic: string;
    council: readonly string[];
  }>;
};

export const DEFAULT_AGENTS_CONFIG: AgentsConfig = Object.freeze({
  models: Object.freeze({
    luna: Object.freeze({ provider: "openai-codex", id: "gpt-5.6-luna" }),
    terra: Object.freeze({ provider: "openai-codex", id: "gpt-5.6-terra" }),
    sol: Object.freeze({ provider: "openai-codex", id: "gpt-5.6-sol" }),
    opus: Object.freeze({ provider: "anthropic", id: "claude-opus-5" }),
    sonnet: Object.freeze({ provider: "anthropic", id: "claude-sonnet-5" }),
  }),
  defaults: Object.freeze({
    scout: "luna",
    reviewer: "sol",
    skeptic: "terra",
    council: Object.freeze(["luna", "sol", "opus", "sonnet"]),
  }),
});
```

Implement strict object/key validation with these exact allowlists:

```ts
const TOP_LEVEL_KEYS = new Set(["models", "defaults"]);
const MODEL_KEYS = new Set(["provider", "id", "extensions", "perspective"]);
const DEFAULT_KEYS = new Set(["scout", "reviewer", "skeptic", "council"]);
const MODEL_NAME = /^[a-z][a-z0-9-]{0,31}$/;
```

Expand `~` in extension paths only after validating each item as a non-empty string. Resolve the default file as `${XDG_CONFIG_HOME:-$HOME/.config}/agent-rules/pi-agents.json`. Return newly frozen objects so callers cannot mutate process-wide policy.

- [ ] **Step 4: Remove the old config loader from `index.ts`**

Replace `MODEL_ALIASES`, `ModelAlias`, `ModelConfig`, `DEFAULT_MODEL_CONFIGS`, `expandHome()`, `loadModelConfigs()`, and `MODEL_CONFIGS` with:

```ts
import {
  loadAgentsConfig,
  type ModelDefinition,
} from "./config.js";

const AGENTS_CONFIG = loadAgentsConfig();
type ModelName = string;
```

Do not yet rewrite the tool schema or execution code; use temporary local adapters if TypeScript requires them. Task 3 removes the remaining hardcoded assumptions.

- [ ] **Step 5: Run tests and typecheck**

Run:

```bash
bun test extensions/pi/agents/config.test.ts
bunx tsc --noEmit --allowImportingTsExtensions --moduleResolution bundler --module preserve --target es2022 extensions/pi/agents/config.ts extensions/pi/agents/index.ts
```

Expected: configuration tests PASS; typecheck PASS. If the repository lacks a local TypeScript executable, use the Pi installation’s existing TypeScript toolchain rather than adding runtime dependencies.

- [ ] **Step 6: Review and request commit approval**

Review `git diff --check` and the task diff. Then stop and request approval for:

```bash
git add extensions/pi/agents/config.ts extensions/pi/agents/config.test.ts extensions/pi/agents/index.ts
git commit -m "feat(agents): load dynamic model catalogs"
```

---

### Task 2: Add exact-route project policy enforcement

**Files:**
- Create: `extensions/pi/agents/policy.ts`
- Create: `extensions/pi/agents/policy.test.ts`

**Interfaces:**
- Consumes: `ModelDefinition` from `config.ts`.
- Produces: `ModelRoute`, `ProjectPolicy`, `findNearestPolicy()`, `loadApplicablePolicies()`, and `assertRouteAllowed()`.
- `assertRouteAllowed(modelName: string, model: ModelDefinition, parentCwd: string, childCwd: string): void` returns only when every applicable policy permits the exact route.

- [ ] **Step 1: Write failing policy tests**

Create `extensions/pi/agents/policy.test.ts`. Use real temporary directories and literal policy files. Include these cases:

```ts
import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { assertRouteAllowed } from "./policy.js";

const roots: string[] = [];
function project(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agents-policy-"));
  roots.push(root);
  return root;
}
afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

function policy(root: string, value: unknown): void {
  fs.mkdirSync(path.join(root, ".pi"), { recursive: true });
  fs.writeFileSync(
    path.join(root, ".pi", "pi-agents-policy.json"),
    `${JSON.stringify(value, null, 2)}\n`,
  );
}

const approved = { provider: "provider-a", id: "org/model" };
const denied = { provider: "provider-b", id: "org/model" };

test("allows global launches when neither cwd has a policy", () => {
  const parent = project();
  const child = project();
  expect(() => assertRouteAllowed("reviewer", denied, parent, child)).not.toThrow();
});

test("compares exact provider and id tuples", () => {
  const root = project();
  policy(root, { version: 1, allowedModels: [approved] });
  expect(() => assertRouteAllowed("reviewer", approved, root, root)).not.toThrow();
  expect(() => assertRouteAllowed("reviewer", denied, root, root)).toThrow(
    "reviewer (provider-b/org/model) is denied",
  );
});

test("a protected parent cannot bypass policy through another child cwd", () => {
  const parent = project();
  const outside = project();
  policy(parent, { version: 1, allowedModels: [approved] });
  expect(() => assertRouteAllowed("reviewer", denied, parent, outside)).toThrow("denied");
});

test("an outside parent cannot bypass a protected child cwd", () => {
  const outside = project();
  const child = project();
  policy(child, { version: 1, allowedModels: [approved] });
  expect(() => assertRouteAllowed("reviewer", denied, outside, child)).toThrow("denied");
});

test("multiple applicable policies intersect", () => {
  const parent = project();
  const child = project();
  policy(parent, { version: 1, allowedModels: [approved] });
  policy(child, { version: 1, allowedModels: [denied] });
  expect(() => assertRouteAllowed("reviewer", approved, parent, child)).toThrow("denied");
});

test("a malformed applicable policy fails closed", () => {
  const root = project();
  policy(root, { version: 2, allowedModels: "anything" });
  expect(() => assertRouteAllowed("reviewer", approved, root, root)).toThrow(
    /pi-agents-policy\.json.*invalid/i,
  );
});
```

Also test nearest-ancestor discovery, symlinked CWD canonicalization, duplicate applicable-policy deduplication, empty allowlists, unknown policy keys, duplicate route tuples, and malformed JSON.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
bun test extensions/pi/agents/policy.test.ts
```

Expected: FAIL because `policy.ts` does not exist.

- [ ] **Step 3: Implement policy discovery and strict parsing**

Create `extensions/pi/agents/policy.ts` with:

```ts
import * as fs from "node:fs";
import * as path from "node:path";
import type { ModelDefinition } from "./config.js";

export type ModelRoute = Readonly<{ provider: string; id: string }>;
export type ProjectPolicy = Readonly<{
  path: string;
  allowedModels: readonly ModelRoute[];
}>;

const POLICY_RELATIVE_PATH = path.join(".pi", "pi-agents-policy.json");
```

Canonicalize existing CWDs with `fs.realpathSync()`. Walk from the canonical directory to its filesystem root and return the nearest existing policy. Parse only `version` and `allowedModels`; require `version === 1`, an array of exact `{provider, id}` objects, non-empty strings, no unknown keys, and no duplicate tuples.

`loadApplicablePolicies(parentCwd, childCwd)` must load both nearest policies, deduplicate by canonical policy path, and throw a basename-only validation error if either existing file is malformed. `assertRouteAllowed()` must require every loaded policy to contain an exact provider-and-ID match.

- [ ] **Step 4: Run tests and typecheck**

Run:

```bash
bun test extensions/pi/agents/config.test.ts extensions/pi/agents/policy.test.ts
bunx tsc --noEmit --allowImportingTsExtensions --moduleResolution bundler --module preserve --target es2022 extensions/pi/agents/config.ts extensions/pi/agents/policy.ts
```

Expected: all tests PASS; typecheck PASS.

- [ ] **Step 5: Review and request commit approval**

Review path traversal, symlink behavior, exact tuple comparison, and error text for accidental absolute-path disclosure. Then stop and request approval for:

```bash
git add extensions/pi/agents/policy.ts extensions/pi/agents/policy.test.ts
git commit -m "feat(agents): enforce project model policies"
```

---

### Task 3: Wire dynamic names and policy preflight into delegate and council

**Files:**
- Create: `extensions/pi/agents/runtime.ts`
- Create: `extensions/pi/agents/runtime.test.ts`
- Modify: `extensions/pi/agents/index.ts:75-702`

**Interfaces:**
- Consumes: `AgentsConfig`, `ModelDefinition`, and `assertRouteAllowed()`.
- Produces: `ResolvedModel`, `resolveModel()`, `preflightDelegate()`, `preflightCouncil()`, `displayModel()`, and `councilPerspective()`.
- `preflightCouncil()` resolves and authorizes every member before the first child is spawned.

- [ ] **Step 1: Write failing runtime-preflight tests**

Create `extensions/pi/agents/runtime.test.ts` using a literal two-model configuration and real temporary project policies:

```ts
import { describe, expect, test } from "bun:test";
import {
  displayModel,
  preflightCouncil,
  preflightDelegate,
} from "./runtime.js";

const config = {
  models: {
    fast: { provider: "provider-a", id: "model-fast" },
    careful: {
      provider: "provider-b",
      id: "org/model-careful",
      perspective: "Check long-term failure modes.",
    },
  },
  defaults: {
    scout: "fast",
    reviewer: "careful",
    skeptic: "careful",
    council: ["fast", "careful"],
  },
} as const;

test("displays honest configured and route identities", () => {
  expect(displayModel("careful", config.models.careful)).toBe(
    "careful (provider-b/org/model-careful)",
  );
});

test("rejects unknown names before launch", () => {
  expect(() => preflightDelegate(config, "missing", process.cwd(), process.cwd())).toThrow(
    "unknown model 'missing'; configured models: careful, fast",
  );
});

test("preflights every council member before returning any launch", () => {
  // Build parent/child temp policy fixtures that allow fast but deny careful.
  // The function must throw and return no partial launch list.
});
```

Complete the last test with the same policy fixture style from Task 2. Add tests proving role defaults come from config, configured perspectives replace hardcoded model switches, absent perspectives use a neutral sentence, duplicate requested members are rejected rather than silently deduplicated, and two to five unique members are accepted.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
bun test extensions/pi/agents/runtime.test.ts
```

Expected: FAIL because `runtime.ts` does not exist.

- [ ] **Step 3: Implement the pure runtime preflight module**

Create `extensions/pi/agents/runtime.ts`:

```ts
import type { AgentsConfig, ModelDefinition } from "./config.js";
import { assertRouteAllowed } from "./policy.js";

export type ResolvedModel = Readonly<{
  name: string;
  definition: Readonly<ModelDefinition>;
}>;

export function displayModel(name: string, model: ModelDefinition): string {
  return `${name} (${model.provider}/${model.id})`;
}

export function resolveModel(config: AgentsConfig, name: string): ResolvedModel {
  const definition = config.models[name];
  if (!definition) {
    throw new Error(
      `unknown model '${name}'; configured models: ${Object.keys(config.models).sort().join(", ")}`,
    );
  }
  return { name, definition };
}
```

Implement `preflightDelegate()` by resolving one model and calling `assertRouteAllowed()` before returning it. Implement `preflightCouncil()` by validating the complete member list, resolving all members, authorizing all members, and only then returning the resolved array. It must not launch processes or mutate state.

- [ ] **Step 4: Make `index.ts` consume dynamic names**

Replace hardcoded model enums and switches:

```ts
const configuredModelNames = Object.keys(AGENTS_CONFIG.models).sort();
if (configuredModelNames.length === 0) throw new Error("Pi agents requires at least one configured model");
const ModelNameField = StringEnum(configuredModelNames);
```

Update `RunResult` to carry:

```ts
model: string;
route: { provider: string; id: string };
```

Change `runChild()` to receive a `ResolvedModel`; use `resolved.definition.provider`, `resolved.definition.id`, and `resolved.definition.extensions`. Build role prompts and council perspectives from the configured name and optional `perspective`, not a hardcoded alias switch.

For `delegate`:

1. Resolve role and requested/default model name.
2. Resolve child CWD.
3. Call `preflightDelegate(AGENTS_CONFIG, modelName, ctx.cwd, childCwd)`.
4. Only after successful preflight call `onUpdate` and `runChild`.

For `council`:

1. Use `params.members ?? AGENTS_CONFIG.defaults.council` without deduplication.
2. Resolve child CWD.
3. Call `preflightCouncil()` for the entire roster.
4. Only after every member passes policy call `onUpdate` and `mapWithLimit`.

Update all call/result rendering to use `displayModel()`. A result heading must look like:

```text
## careful (provider-b/org/model-careful)
```

Do not expose local config paths or provider-extension paths in tool descriptions or model-visible output.

- [ ] **Step 5: Prove denied councils spawn zero children**

Add a test seam to `index.ts` only if needed:

```ts
export type SpawnChild = typeof runChild;
export function createAgentsExtension(deps: { spawnChild?: SpawnChild } = {}) { /* register tools */ }
export default createAgentsExtension();
```

Prefer testing the pure `preflightCouncil()` boundary. If a registration-level test is practical, register into a minimal fake `ExtensionAPI`, provide a fake `spawnChild` that increments a counter, execute a council containing one denied route, and assert `spawnCalls === 0`.

- [ ] **Step 6: Run the focused suite and a fresh Pi command-discovery smoke test**

Run:

```bash
bun test extensions/pi/agents/config.test.ts extensions/pi/agents/policy.test.ts extensions/pi/agents/runtime.test.ts
printf '%s\n' '{"id":"commands","type":"get_commands"}' \
  | pi --mode rpc --no-session \
  | grep -E '"name":"(delegate|council)"'
```

Expected: all Bun tests PASS; both extension commands appear; no extension-load error appears on stderr.

- [ ] **Step 7: Review and request commit approval**

Review the exact spawn ordering and verify policy preflight occurs before `onUpdate`, task construction, or child process creation. Then stop and request approval for:

```bash
git add extensions/pi/agents/index.ts extensions/pi/agents/runtime.ts extensions/pi/agents/runtime.test.ts
git commit -m "feat(agents): authorize dynamic model routes"
```

---

### Task 4: Document configuration and add CI coverage

**Files:**
- Modify: `setup/pi-agents.example.json`
- Create: `setup/pi-agents-policy.example.json`
- Modify: `extensions/pi/agents/README.md`
- Modify: `docs/setup.md:65-82`
- Modify: `.github/workflows/ci.yml`
- Modify: `setup/test-fresh-install.sh:115-135`

**Interfaces:**
- Consumes: the exact schemas implemented by `config.ts` and `policy.ts`.
- Produces: copyable public examples and a CI `agents-extension` job.

- [ ] **Step 1: Update the public model configuration example**

Replace `setup/pi-agents.example.json` with a complete generic example matching the parser:

```json
{
  "models": {
    "fast": {
      "provider": "example-provider",
      "id": "example-fast-model"
    },
    "careful": {
      "provider": "example-provider",
      "id": "example-careful-model",
      "perspective": "Challenge assumptions and inspect long-term failure modes."
    }
  },
  "defaults": {
    "scout": "fast",
    "reviewer": "careful",
    "skeptic": "careful",
    "council": ["fast", "careful"]
  }
}
```

Do not include private providers, endpoints, project names, or personal model preferences.

- [ ] **Step 2: Add a generic project-policy example**

Create `setup/pi-agents-policy.example.json`:

```json
{
  "version": 1,
  "allowedModels": [
    {
      "provider": "example-provider",
      "id": "example-approved-model"
    }
  ]
}
```

- [ ] **Step 3: Update extension and setup documentation**

Document:

- The config file is authoritative when present.
- Model keys are the exact names accepted by `delegate.model` and `council.members`.
- Defaults must reference configured names.
- Project policy compares exact provider/model routes, not names.
- Parent and child CWD policies both apply and intersect.
- Invalid policies fail closed.
- A non-retention-safe model may be globally configured but must not appear in a sensitive project’s allowlist.
- `/reload` or a fresh Pi session is required after changing the global model catalog because schemas are built at extension load.

- [ ] **Step 4: Extend fresh-install assertions**

Add literal checks after the existing extension-link assertion:

```bash
[ -f "$REPO/setup/pi-agents.example.json" ] \
  || fail "Pi agents model-config example missing"
[ -f "$REPO/setup/pi-agents-policy.example.json" ] \
  || fail "Pi agents project-policy example missing"
pass "Pi agents configuration examples present"
```

Do not copy either example into the fake HOME automatically; installation must not invent provider choices or project policies.

- [ ] **Step 5: Add Bun tests to CI**

Add this independent job to `.github/workflows/ci.yml`:

```yaml
  agents-extension:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: latest
      - name: Test bounded Pi agents configuration and policy
        run: bun test extensions/pi/agents
```

Keep the existing privacy, shellcheck, config-contracts, and fresh-install jobs unchanged.

- [ ] **Step 6: Run documentation, privacy, and complete repository checks**

Run:

```bash
bun test extensions/pi/agents
bash setup/test-fresh-install.sh
bash setup/test-workflows.sh
bash setup/test-compaction-config.sh
./check-privacy.sh
./setup/doctor.sh
git diff --check
```

Expected: every command exits 0. `doctor.sh` may print documented warnings for intentionally unconfigured device-local resources, but must not print `DOCTOR FOUND ISSUES`.

- [ ] **Step 7: Review and request commit approval**

Inspect the entire diff for personal identifiers and real provider configuration. Then stop and request approval for:

```bash
git add .github/workflows/ci.yml setup/pi-agents.example.json setup/pi-agents-policy.example.json setup/test-fresh-install.sh extensions/pi/agents/README.md docs/setup.md
git commit -m "docs(agents): explain model and project policy"
```

---

### Task 5: Final security verification and deployment handoff

**Files:**
- Modify only if verification reveals a defect: files from Tasks 1-4
- Do not commit: `~/.config/agent-rules/pi-agents.json`
- Do not commit: any project-local `.pi/pi-agents-policy.json` containing device-specific route choices unless that project owner separately approves it

**Interfaces:**
- Produces: verified branch, exact configuration instructions, and evidence that the old third-party package is absent.

- [ ] **Step 1: Run mutation-oriented policy checks**

Temporarily mutate test fixtures, not production files, to verify the suite catches:

- same model ID under a different provider
- approved alias remapped to a denied route
- protected parent with child CWD outside the project
- unprotected parent with child CWD inside the project
- malformed policy JSON
- a council where the first member is allowed and the second is denied

Run:

```bash
bun test extensions/pi/agents
```

Expected: each intentionally wrong expectation fails; restore the tests and confirm the suite passes.

- [ ] **Step 2: Verify the complete branch**

Run:

```bash
bun test extensions/pi/agents
bash setup/test-fresh-install.sh
bash setup/test-workflows.sh
bash setup/test-compaction-config.sh
./check-privacy.sh
git diff --check
git status --short --branch
```

Expected: all tests pass; privacy and diff checks exit 0; status contains only intentional plan/spec files or is clean after approved commits.

- [ ] **Step 3: Verify runtime discovery without invoking a model**

After linking the branch extension into a test Pi home, run:

```bash
printf '%s\n' '{"id":"commands","type":"get_commands"}' \
  | pi --mode rpc --no-session
```

Expected: the response lists extension commands `delegate` and `council`; stderr contains no extension-load error.

- [ ] **Step 4: Prepare private deployment values for human review**

Provide, but do not commit or install without explicit approval:

- a complete machine-local `~/.config/agent-rules/pi-agents.json` with honest model names and exact routes
- a project-local `.pi/pi-agents-policy.json` containing only that project’s approved routes
- the exact removal check for conflicting third-party orchestration packages

The handoff must explicitly warn that globally configuring a model does not authorize it inside a protected project.

- [ ] **Step 5: Request final review and publication decisions**

Report:

- commits and changed files
- exact test outputs
- unresolved security assumptions
- whether the remote feature branch and PR need updating

Do not push, update a PR, merge, install private configuration, or delete the abandoned third-party checkout without separate explicit approval for each intended remote or destructive action.
