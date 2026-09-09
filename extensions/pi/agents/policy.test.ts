import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  assertRouteAllowed,
  findNearestPolicy,
  loadApplicablePolicies,
} from "./policy.js";

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

function rawPolicy(root: string, contents: string): void {
  fs.mkdirSync(path.join(root, ".pi"), { recursive: true });
  fs.writeFileSync(path.join(root, ".pi", "pi-agents-policy.json"), contents);
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

test("finds the nearest policy in an ancestor directory", () => {
  const root = project();
  const child = path.join(root, "nested", "deeper");
  fs.mkdirSync(child, { recursive: true });
  policy(root, { version: 1, allowedModels: [approved] });

  expect(findNearestPolicy(child)?.path).toBe(
    fs.realpathSync(path.join(root, ".pi", "pi-agents-policy.json")),
  );
});

test("canonicalizes a symlinked cwd before discovering its policy", () => {
  const root = project();
  const link = `${root}-link`;
  roots.push(link);
  fs.symlinkSync(root, link, "dir");
  policy(root, { version: 1, allowedModels: [approved] });

  expect(findNearestPolicy(link)?.path).toBe(
    fs.realpathSync(path.join(root, ".pi", "pi-agents-policy.json")),
  );
});

test("deduplicates a policy that governs both cwd arguments", () => {
  const root = project();
  policy(root, { version: 1, allowedModels: [approved], council: ["fast", "careful"] });

  const policies = loadApplicablePolicies(root, root);
  expect(policies).toHaveLength(1);
  expect(policies[0]?.council).toEqual(["fast", "careful"]);
});

test("parses an optional scoped council roster", () => {
  const root = project();
  policy(root, {
    version: 1,
    allowedModels: [approved],
    council: ["fast", "careful"],
  });

  expect(loadApplicablePolicies(root, root)[0]?.council).toEqual(["fast", "careful"]);
});

test("retains ordered rosters from distinct applicable policies", () => {
  const parent = project();
  const child = project();
  policy(parent, {
    version: 1,
    allowedModels: [],
    council: ["fast", "careful"],
  });
  policy(child, {
    version: 1,
    allowedModels: [],
    council: ["careful", "fast"],
  });

  expect(loadApplicablePolicies(parent, child).map((item) => item.council)).toEqual([
    ["fast", "careful"],
    ["careful", "fast"],
  ]);
});

test("leaves an omitted scoped council roster absent", () => {
  const root = project();
  policy(root, { version: 1, allowedModels: [approved] });

  expect(loadApplicablePolicies(root, root)[0]?.council).toBeUndefined();
});

test.each([
  [{ version: 1, allowedModels: [approved], council: ["fast"] }, "2 to 5"],
  [{ version: 1, allowedModels: [approved], council: ["fast", "fast"] }, "unique"],
  [{ version: 1, allowedModels: [approved], council: ["Bad Name", "careful"] }, "valid model name"],
  [{ version: 1, allowedModels: [approved], council: ["a", "b", "c", "d", "e", "f"] }, "2 to 5"],
  [{ version: 1, allowedModels: [approved], council: "fast" }, "council must be an array"],
] as const)("rejects invalid scoped council %#", (value, message) => {
  const root = project();
  policy(root, value);
  expect(() => loadApplicablePolicies(root, root)).toThrow(message);
});

test("an empty allowlist denies every route", () => {
  const root = project();
  policy(root, { version: 1, allowedModels: [] });

  expect(() => assertRouteAllowed("reviewer", approved, root, root)).toThrow("denied");
});

test.each([
  [{ version: 1, allowedModels: [approved], extra: true }, "unknown policy key"],
  [{ version: 1, allowedModels: [{ ...approved, extra: true }] }, "unknown route key"],
  [{ version: 1, allowedModels: [approved, approved] }, "duplicate route"],
  [{ version: 1 }, "allowedModels"],
  [{ allowedModels: [approved] }, "version"],
  [{ version: 2, allowedModels: [approved] }, "version must be 1"],
  [{ version: 1, allowedModels: [{ provider: "", id: "model" }] }, "provider"],
  [{ version: 1, allowedModels: [{ provider: "provider", id: "" }] }, "id"],
] as const)("rejects invalid policy %#", (value, message) => {
  const root = project();
  policy(root, value);

  expect(() => loadApplicablePolicies(root, root)).toThrow(message);
});

test("rejects malformed JSON without exposing the absolute policy path", () => {
  const root = project();
  rawPolicy(root, "{ not valid json\n");

  let errorMessage = "";
  try {
    loadApplicablePolicies(root, root);
  } catch (error) {
    errorMessage = String(error);
  }
  expect(errorMessage).toMatch(/pi-agents-policy\.json.*invalid/i);
  expect(errorMessage).not.toContain(root);
});
