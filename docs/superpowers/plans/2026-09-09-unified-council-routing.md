# Unified Council Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bounded Pi agents extension the single runtime for `/council`, with catalog-backed model names, scoped project rosters, exact-route authorization, and fail-closed preflight before any child launch.

**Architecture:** Keep model-catalog parsing, project-policy discovery, and runtime resolution in pure TypeScript modules. The extension entrypoint builds schemas from the loaded catalog, resolves scoped defaults from the parent and child CWDs, authorizes the complete roster before progress or spawning, and then invokes the existing isolated child runner. The public repository documents generic configuration only; private deployment cleanup remains outside this change.

**Tech Stack:** TypeScript, Bun test, Pi extension API, TypeBox, Node filesystem/path APIs, Bash installer tests, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-unified-council-routing-design.md`

## Global Constraints

- Keep `extensions/pi/agents/child-guard.ts` read-only and preserve its existing path, credential, symlink, hardlink, size, and output protections.
- Child Pi processes must continue using `--no-session`, `--no-extensions`, `--no-skills`, `--no-prompt-templates`, and `--no-context-files`.
- Compare project policy against the resolved `(provider, id)` tuple, never the configured model name.
- Apply every policy governing either the parent session CWD or requested child CWD; multiple policies intersect.
- An existing malformed policy denies launch before `spawn()` and never degrades to unrestricted execution.
- Keep device-specific providers, model IDs, paths, and project policies out of this public repository.
- Scoped council arrays are order-sensitive, contain 2–5 unique valid names, and must resolve against the complete configured catalog.
- Explicit council members bypass scoped default selection, not route authorization.
- All council children use the `reviewer` role; model-specific behavior comes only from configured perspectives and the neutral fallback.
- The entire council roster is preflighted before progress updates, task construction, or child spawning.
- Do not modify or rename the public `workflows/council` workflow, `workflow-map` entry, or global `/council` command for private deployment cleanup.
- Do not install private configuration, delete files, commit, push, merge, publish, or update a remote without a separate explicit approval for that exact action.

---

### Task 1: Add scoped council overrides to exact-route project policy

**Files:**
- Modify: `extensions/pi/agents/policy.ts`
- Modify: `extensions/pi/agents/policy.test.ts`

**Interfaces:**
- `ProjectPolicy` gains `council?: readonly string[]`.
- `loadApplicablePolicies(parentCwd, childCwd)` continues to return canonical, deduplicated policies.
- `assertRouteAllowed()` continues to authorize every exact route against every applicable policy.

- [ ] **Step 1: Add failing scoped-policy tests**

Extend `policy.test.ts` with these behaviors before changing `policy.ts`:

```ts
test("parses an optional scoped council roster", () => {
  const root = project();
  policy(root, {
    version: 1,
    allowedModels: [approved],
    council: ["fast", "careful"],
  });

  expect(loadApplicablePolicies(root, root)[0]?.council).toEqual(["fast", "careful"]);
});

test.each([
  [{ version: 1, allowedModels: [approved], council: ["fast"] }, "2 to 5"],
  [{ version: 1, allowedModels: [approved], council: ["fast", "fast"] }, "unique"],
  [{ version: 1, allowedModels: [approved], council: ["Bad Name", "careful"] }, "valid model name"],
  [{ version: 1, allowedModels: [approved], council: ["fast", "careful"], extra: true }, "unknown policy key"],
] as const)("rejects invalid scoped council %#", (value, message) => {
  const root = project();
  policy(root, value);
  expect(() => loadApplicablePolicies(root, root)).toThrow(message);
});
```

Add a six-member case and a non-array `council` case. Add a fixture with the same policy reached through parent and child CWDs and assert the returned policy appears once with its roster intact. Add a fixture with a parent `council` override and a child `council` override so the runtime tests can distinguish both policies later.

- [ ] **Step 2: Run the scoped policy tests and verify RED**

Run:

```bash
bun test extensions/pi/agents/policy.test.ts
```

Expected: the new optional-roster test fails because `ProjectPolicy` and the parser do not yet accept `council`; existing exact-route tests remain green.

- [ ] **Step 3: Implement strict optional council parsing**

In `policy.ts`, expand the accepted policy keys to `version`, `allowedModels`, and `council`. Validate an optional `council` as an array of 2–5 unique names matching `/^[a-z][a-z0-9-]{0,31}$/`. Preserve order, reject unknown keys and duplicate names, freeze the copied array, and leave it absent when omitted. Keep route validation and canonical policy-path error messages unchanged.

The returned object must have this shape:

```ts
return Object.freeze({
  path: fs.realpathSync(policyPath),
  allowedModels: Object.freeze(routes),
  ...(council === undefined ? {} : { council: Object.freeze(council) }),
});
```

Do not resolve names against the model catalog in `policy.ts`; the policy module has no catalog context. Runtime resolution performs that check before launch.

- [ ] **Step 4: Run policy tests and typecheck**

Run:

```bash
bun test extensions/pi/agents/policy.test.ts
bunx tsc --noEmit --allowImportingTsExtensions --moduleResolution bundler --module preserve --target es2022 extensions/pi/agents/config.ts extensions/pi/agents/policy.ts
```

Expected: all policy tests pass and TypeScript exits 0.

---

### Task 2: Resolve scoped defaults and complete pure runtime preflight

**Files:**
- Modify: `extensions/pi/agents/runtime.ts`
- Modify: `extensions/pi/agents/runtime.test.ts`

**Interfaces:**
- Consumes: `AgentsConfig`, `ModelDefinition`, `ProjectPolicy`, `loadApplicablePolicies()`, and `assertRouteAllowed()`.
- Produces: `ResolvedModel`, `resolveModel()`, `resolveCouncilMembers()`, `preflightDelegate()`, `preflightCouncil()`, `displayModel()`, and `councilPerspective()`.

- [ ] **Step 1: Add failing roster-resolution tests**

Import `resolveCouncilMembers` and add tests using the existing `config` and temporary policy helper:

```ts
test("uses the global configured council when no policy supplies an override", () => {
  const root = project();
  expect(resolveCouncilMembers(config, undefined, root, root)).toEqual(["fast", "careful"]);
});

test("uses a scoped override from the parent or child CWD", () => {
  const parent = project();
  const child = project();
  policy(parent, {
    version: 1,
    allowedModels: [{ provider: "provider-a", id: "model-fast" }],
    council: ["fast", "careful"],
  });
  expect(resolveCouncilMembers(config, undefined, parent, child)).toEqual(["fast", "careful"]);
});

test("deduplicates identical scoped arrays", () => {
  const parent = project();
  const child = project();
  policy(parent, { version: 1, allowedModels: [], council: ["fast", "careful"] });
  policy(child, { version: 1, allowedModels: [], council: ["fast", "careful"] });
  expect(resolveCouncilMembers(config, undefined, parent, child)).toEqual(["fast", "careful"]);
});

test("rejects conflicting parent and child scoped arrays", () => {
  const parent = project();
  const child = project();
  policy(parent, { version: 1, allowedModels: [], council: ["fast", "careful"] });
  policy(child, { version: 1, allowedModels: [], council: ["careful", "fast"] });
  expect(() => resolveCouncilMembers(config, undefined, parent, child)).toThrow(/conflicting council/i);
});

test("explicit members bypass scoped default selection", () => {
  const root = project();
  policy(root, { version: 1, allowedModels: [], council: ["fast", "careful"] });
  expect(resolveCouncilMembers(config, ["careful", "fast"], root, root)).toEqual(["careful", "fast"]);
});
```

Add a test proving a scoped override naming an unconfigured model throws the same configured-name error as `resolveModel()`. Add a test proving explicit duplicate members are rejected rather than deduplicated. Keep the existing perspective tests: configured text must be returned verbatim after trimming only for the presence check, and absent/blank perspective must return `Review independently and let the evidence determine the conclusion.`.

- [ ] **Step 2: Run runtime tests and verify RED**

Run:

```bash
bun test extensions/pi/agents/runtime.test.ts
```

Expected: the new resolver tests fail because no scoped-roster resolver exists.

- [ ] **Step 3: Implement scoped roster selection**

Import `loadApplicablePolicies()` into `runtime.ts` and implement:

```ts
export function resolveCouncilMembers(
  config: AgentsConfig,
  explicitMembers: readonly string[] | undefined,
  parentCwd: string,
  childCwd: string,
): readonly string[] {
  if (explicitMembers !== undefined) return Object.freeze([...explicitMembers]);

  const overrides = loadApplicablePolicies(parentCwd, childCwd)
    .map((policy) => policy.council)
    .filter((council): council is readonly string[] => council !== undefined);
  if (overrides.length === 0) return config.defaults.council;

  const first = overrides[0]!;
  if (overrides.some((council) => council.length !== first.length || council.some((name, i) => name !== first[i]))) {
    throw new Error("Conflicting council defaults from applicable project policies.");
  }
  return first;
}
```

`preflightCouncil()` must validate 2–5 members, reject duplicates, resolve every name, authorize every resolved route, and return only after the complete loop succeeds. It must not mutate state or launch children. `preflightDelegate()` must resolve and authorize one route. `councilPerspective()` must use only `definition.perspective?.trim()` and the neutral fallback; do not retain any alias switch.

- [ ] **Step 4: Run the pure runtime suite and typecheck**

Run:

```bash
bun test extensions/pi/agents/config.test.ts extensions/pi/agents/policy.test.ts extensions/pi/agents/runtime.test.ts
bunx tsc --noEmit --allowImportingTsExtensions --moduleResolution bundler --module preserve --target es2022 extensions/pi/agents/config.ts extensions/pi/agents/policy.ts extensions/pi/agents/runtime.ts
```

Expected: all focused tests pass and TypeScript exits 0.

---

### Task 3: Wire the dispatcher to dynamic routes and preflight ordering

**Files:**
- Modify: `extensions/pi/agents/index.ts`
- Modify: `extensions/pi/agents/runtime.test.ts`
- Modify: `extensions/pi/agents/index.test.ts` if a registration seam test is needed

**Interfaces:**
- Consumes: the Task 1 config/policy modules and Task 2 runtime functions.
- Produces: dynamic TypeBox schemas, route-aware `RunResult`, `createAgentsExtension()`, and a default extension registration with exactly one public `council` command in this extension.

- [ ] **Step 1: Add failing registration-level tests**

Create `index.test.ts` only if the existing runtime test cannot exercise registration. Use a fake extension API and injected configuration/launcher. The fake launcher records options and returns a bounded successful `RunResult` without starting a process.

The denied-council test must use a project policy allowing only `fast`, request `fast` plus `careful`, and assert all of the following:

```ts
expect(() => councilTool.execute("id", {
  question: "test",
  members: ["fast", "careful"],
}, new AbortController().signal, onUpdate, { cwd: root } as any)).rejects.toThrow("careful");
expect(spawnCalls).toBe(0);
expect(updateCalls).toBe(0);
```

Add an approved-council test asserting two launcher calls receive the exact configured definitions and that the first progress update occurs only after preflight. Add a command test that invokes the registered `council` handler and verifies its user message says to use the council tool without embedding the configured roster names.

- [ ] **Step 2: Run the registration tests and verify RED**

Run:

```bash
bun test extensions/pi/agents/index.test.ts
```

Expected: FAIL because registration has no injectable factory and the dispatcher currently updates before policy checks.

- [ ] **Step 3: Remove the obsolete council catalog from the dispatcher**

Remove the `loadCouncilConfig()` import, `COUNCIL_CONFIG`, and all `council.json`-derived constants from `index.ts`. Use `config.defaults.council` only through the scoped resolver. Do not alter `workflows/council`, `workflow-map`, or the global command name.

Build model enums from the active config at extension-factory creation time. Keep the non-empty catalog guard and dynamic names. The council tool description and default preview must say `configured scoped default` when `members` is omitted; they must not display the normal roster before execution resolves CWD policies.

- [ ] **Step 4: Make child execution consume `ResolvedModel`**

Change the child-runner options to receive a `ResolvedModel`. Use `resolved.definition.provider`, `.id`, and `.extensions` for the Pi invocation. Preserve these isolation flags exactly:

```text
--no-session --no-extensions --no-skills --no-prompt-templates --no-context-files
```

Change `RunResult` to carry:

```ts
model: string;
route: { provider: string; id: string };
```

Populate `route` from the resolved definition and render result headings with `displayModel(result.model, result.route)`. Progress and call previews for explicit members should likewise show configured names and exact routes. Do not expose config-file or provider-extension paths.

- [ ] **Step 5: Remove model-name behavior switches**

Replace alias-specific thinking defaults with role-based defaults: scouts default to `medium`, reviewers default to `high`, and council members use the reviewer role. Keep user-provided `thinking` unchanged. Build every council perspective from the configured `perspective` field, using the neutral fallback when absent or blank. Do not branch on `luna`, `terra`, `sol`, `opus`, or `sonnet`.

- [ ] **Step 6: Add the extension factory and enforce ordering**

Refactor registration into:

```ts
export type SpawnChild = (options: {
  resolved: ResolvedModel;
  role: Role;
  thinking: ThinkingLevel;
  task: string;
  cwd: string;
  signal?: AbortSignal;
}) => Promise<RunResult>;

export function createAgentsExtension(deps: {
  config?: AgentsConfig;
  spawnChild?: SpawnChild;
} = {}): (pi: ExtensionAPI) => void;

export default createAgentsExtension();
```

For `delegate`, resolve role/model name, resolve child CWD, call `preflightDelegate(config, name, ctx.cwd, childCwd)`, then call `onUpdate`, construct the task, and invoke the injected/default launcher.

For `council`, select `params.members` when explicitly present, otherwise call `resolveCouncilMembers(config, undefined, ctx.cwd, childCwd)`. Call `preflightCouncil()` for the entire list before `onUpdate`, task construction, `mapWithLimit`, or a launcher call. Do not use `new Set()` on requested members. Keep concurrency, output caps, cancellation, and child isolation unchanged.

- [ ] **Step 7: Run focused integration, typecheck, and command smoke tests**

Run:

```bash
bun test extensions/pi/agents
bunx tsc --noEmit --allowImportingTsExtensions --moduleResolution bundler --module preserve --target es2022 extensions/pi/agents/config.ts extensions/pi/agents/policy.ts extensions/pi/agents/runtime.ts extensions/pi/agents/index.ts
printf '%s\n' '{"id":"commands","type":"get_commands"}' \
  | pi --mode rpc --no-session \
  | grep -E '"name":"(delegate|council)"'
```

Expected: all extension tests pass, TypeScript exits 0, and the installed extension reports its `delegate` and `council` commands without an extension-load error. Public tests must not assert the private deployment's final global command count.

---

### Task 4: Unify public examples, documentation, and CI

**Files:**
- Modify: `setup/pi-agents.example.json`
- Create: `setup/pi-agents-policy.example.json`
- Modify: `extensions/pi/agents/README.md`
- Modify: `docs/setup.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `setup/test-fresh-install.sh`

**Interfaces:**
- Documentation and examples exactly match the strict config and policy parsers.
- Fresh-install tests verify example presence but do not copy provider choices or project policy into fake HOME.
- CI runs the bounded extension tests independently of shell/config-contract jobs.

- [ ] **Step 1: Replace the public model example with generic routes**

Use this complete content in `setup/pi-agents.example.json`:

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

- [ ] **Step 2: Add the generic policy example**

Create `setup/pi-agents-policy.example.json` with:

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

- [ ] **Step 3: Rewrite extension and setup documentation**

Document that `~/.config/agent-rules/pi-agents.json` is authoritative when present; model keys are the exact names accepted by the tools; defaults must reference configured names; `extensions` paths are trusted code; policies compare exact provider/ID tuples; parent and child CWD policies intersect; optional `council` overrides are order-sensitive; malformed policies fail closed; an absent policy is not a privacy guarantee; and `/reload` or a fresh Pi session is required after catalog changes because schemas are built at extension load.

Remove public instructions for the separate `council.json` catalog. Do not document private provider routes, project names, or private maintenance-skill changes.

- [ ] **Step 4: Add fresh-install example assertions**

After the existing Pi extension-link assertion in `setup/test-fresh-install.sh`, add:

```bash
[ -f "$REPO/setup/pi-agents.example.json" ] \
  || fail "Pi agents model-config example missing"
[ -f "$REPO/setup/pi-agents-policy.example.json" ] \
  || fail "Pi agents project-policy example missing"
pass "Pi agents configuration examples present"
```

Leave existing public `workflows/council` assertions unchanged. Do not copy either example into fake HOME.

- [ ] **Step 5: Add the independent Bun CI job**

Add this job to `.github/workflows/ci.yml` without changing existing jobs:

```yaml
  agents-extension:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: latest
      - name: Test bounded Pi agents configuration, policy, and runtime
        run: bun test extensions/pi/agents
```

- [ ] **Step 6: Run public documentation and repository checks**

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

---

### Task 5: Gated obsolete-file cleanup and final verification

**Files:**
- Delete only after separate explicit approval: `extensions/pi/agents/council-config.ts`
- Delete only after separate explicit approval: `extensions/pi/agents/council-config.test.ts`
- Delete only after separate explicit approval: `setup/council.example.json`
- Modify only if verification exposes a defect: files from Tasks 1–4

**Interfaces:**
- The unified catalog is the only public model-roster source of truth.
- Private deployment cleanup is verified separately and is not performed by public tests.

- [ ] **Step 1: Stop for deletion approval**

Before removing the three obsolete public experiment files, request approval naming those exact paths and the deletion action. Until approval arrives, leave them untouched and report that the public runtime no longer imports them but the files remain in the worktree.

- [ ] **Step 2: After approval, remove obsolete source and tests**

Delete only the approved obsolete files. Confirm `rg -n "council-config|council\.json|PI_COUNCIL_CONFIG" extensions/pi setup docs README.md` returns no public runtime/documentation references, while `workflows/council`, `workflow-map`, and `/council` remain present.

- [ ] **Step 3: Run mutation-oriented policy regressions without changing production files**

Temporarily change only disposable test fixtures to verify the suite rejects: the same ID under another provider, an alias remapped to a denied route, a protected parent with an outside child CWD, an outside parent with a protected child CWD, malformed JSON, and a council whose first member passes while the second is denied. Restore the fixtures and run:

```bash
bun test extensions/pi/agents
```

- [ ] **Step 4: Run final public verification**

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

Expected: all tests and checks pass; status contains only intentional uncommitted implementation/spec/plan files because commit approval has not been granted.

- [ ] **Step 5: Prepare, but do not perform, private deployment handoff**

Report the private-only follow-up: create machine-local `~/.config/agent-rules/pi-agents.json`, add exact protected-project `.pi/pi-agents-policy.json`, remove the duplicate project prompt only after verification, and rename only the private maintenance skill `council-models` if it collides. State explicitly that global configuration does not authorize a route inside a protected project. Do not install, delete, commit, push, merge, or update a PR.
