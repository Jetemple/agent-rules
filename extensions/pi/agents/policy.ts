import * as fs from "node:fs";
import * as path from "node:path";
import type { ModelDefinition } from "./config.js";

export type ModelRoute = Readonly<{
  provider: string;
  id: string;
}>;

export type ProjectPolicy = Readonly<{
  path: string;
  allowedModels: readonly ModelRoute[];
  council?: readonly string[];
}>;

const POLICY_RELATIVE_PATH = path.join(".pi", "pi-agents-policy.json");
const POLICY_KEYS = new Set(["version", "allowedModels", "council"]);
const ROUTE_KEYS = new Set(["provider", "id"]);
const COUNCIL_NAME = /^[a-z][a-z0-9-]{0,31}$/;

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOwn(value: UnknownRecord, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function policyLabel(policyPath: string): string {
  return path.basename(policyPath) || "pi-agents-policy.json";
}

function invalid(policyPath: string, message: string): never {
  throw new Error(`${policyLabel(policyPath)}: invalid policy: ${message}`);
}

function assertKeys(value: UnknownRecord, allowed: ReadonlySet<string>, policyPath: string, kind: string): void {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) invalid(policyPath, `unknown ${kind} '${key}'`);
  }
}

function parsePolicy(policyPath: string, displayPath = policyPath): ProjectPolicy {
  let source: string;
  try {
    source = fs.readFileSync(policyPath, "utf8");
  } catch {
    invalid(displayPath, "cannot read policy file");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(source);
  } catch {
    invalid(displayPath, "invalid JSON");
  }

  if (!isRecord(parsed)) invalid(displayPath, "configuration must be an object");
  assertKeys(parsed, POLICY_KEYS, displayPath, "policy key");
  if (!hasOwn(parsed, "version")) invalid(displayPath, "missing version");
  if (parsed.version !== 1) invalid(displayPath, "version must be 1");
  if (!hasOwn(parsed, "allowedModels")) invalid(displayPath, "missing allowedModels");
  if (!Array.isArray(parsed.allowedModels)) invalid(displayPath, "allowedModels must be an array");

  const routes: ModelRoute[] = [];
  const seen = new Set<string>();
  for (const [index, rawRoute] of parsed.allowedModels.entries()) {
    if (!isRecord(rawRoute)) invalid(displayPath, `allowedModels[${index}] must be an object`);
    assertKeys(rawRoute, ROUTE_KEYS, displayPath, "route key");
    if (!hasOwn(rawRoute, "provider")) invalid(displayPath, `allowedModels[${index}] is missing provider`);
    if (!hasOwn(rawRoute, "id")) invalid(displayPath, `allowedModels[${index}] is missing id`);
    if (typeof rawRoute.provider !== "string" || rawRoute.provider.trim() === "") {
      invalid(displayPath, `allowedModels[${index}].provider must be a non-empty string`);
    }
    if (typeof rawRoute.id !== "string" || rawRoute.id.trim() === "") {
      invalid(displayPath, `allowedModels[${index}].id must be a non-empty string`);
    }

    const routeKey = JSON.stringify([rawRoute.provider, rawRoute.id]);
    if (seen.has(routeKey)) invalid(displayPath, `allowedModels contains duplicate route at index ${index}`);
    seen.add(routeKey);
    routes.push(Object.freeze({ provider: rawRoute.provider, id: rawRoute.id }));
  }

  let council: string[] | undefined;
  if (hasOwn(parsed, "council")) {
    if (!Array.isArray(parsed.council)) invalid(displayPath, "council must be an array");
    if (parsed.council.length < 2 || parsed.council.length > 5) {
      invalid(displayPath, "council must contain 2 to 5 members");
    }

    council = [];
    const councilNames = new Set<string>();
    for (const [index, rawName] of parsed.council.entries()) {
      if (typeof rawName !== "string" || !COUNCIL_NAME.test(rawName)) {
        invalid(displayPath, `council[${index}] must be a valid model name`);
      }
      if (councilNames.has(rawName)) {
        invalid(displayPath, `council must contain unique members; duplicate member '${rawName}'`);
      }
      councilNames.add(rawName);
      council.push(rawName);
    }
  }

  return Object.freeze({
    path: fs.realpathSync(policyPath),
    allowedModels: Object.freeze(routes),
    ...(council === undefined ? {} : { council: Object.freeze(council) }),
  });
}

function canonicalDirectory(cwd: string): string {
  let canonical: string;
  try {
    canonical = fs.realpathSync(cwd);
  } catch {
    throw new Error("Agent cwd is not accessible");
  }

  try {
    if (!fs.statSync(canonical).isDirectory()) throw new Error("not a directory");
  } catch {
    throw new Error("Agent cwd is not a directory");
  }
  return canonical;
}

function existingPolicyPath(candidate: string): string | undefined {
  try {
    fs.lstatSync(candidate);
    return candidate;
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") return undefined;
    invalid(candidate, "cannot inspect policy file");
  }
}

export function findNearestPolicy(cwd: string): ProjectPolicy | undefined {
  let current = canonicalDirectory(cwd);

  while (true) {
    const candidate = path.join(current, POLICY_RELATIVE_PATH);
    const existing = existingPolicyPath(candidate);
    if (existing !== undefined) {
      let canonicalPolicyPath: string;
      try {
        canonicalPolicyPath = fs.realpathSync(existing);
      } catch {
        invalid(existing, "cannot resolve policy file");
      }
      return parsePolicy(canonicalPolicyPath, existing);
    }

    const parent = path.dirname(current);
    if (parent === current) return undefined;
    current = parent;
  }
}

export function loadApplicablePolicies(parentCwd: string, childCwd: string): readonly ProjectPolicy[] {
  const policies: ProjectPolicy[] = [];
  const seen = new Set<string>();
  for (const cwd of [parentCwd, childCwd]) {
    const policy = findNearestPolicy(cwd);
    if (!policy || seen.has(policy.path)) continue;
    seen.add(policy.path);
    policies.push(policy);
  }
  return Object.freeze(policies);
}

function routeMatches(route: ModelRoute, model: ModelRoute): boolean {
  return route.provider === model.provider && route.id === model.id;
}

export function assertRouteAllowed(
  modelName: string,
  model: ModelDefinition,
  parentCwd: string,
  childCwd: string,
): void {
  const route = { provider: model.provider, id: model.id };
  for (const policy of loadApplicablePolicies(parentCwd, childCwd)) {
    if (!policy.allowedModels.some((allowed) => routeMatches(allowed, route))) {
      throw new Error(`${modelName} (${model.provider}/${model.id}) is denied by project policy`);
    }
  }
}
