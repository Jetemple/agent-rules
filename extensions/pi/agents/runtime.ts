import type { AgentsConfig, ModelDefinition } from "./config.js";
import { assertRouteAllowed, loadApplicablePolicies } from "./policy.js";

const MIN_COUNCIL_MEMBERS = 2;
const MAX_COUNCIL_MEMBERS = 5;
const NEUTRAL_PERSPECTIVE = "Review independently and let the evidence determine the conclusion.";

export type ResolvedModel = Readonly<{
  name: string;
  definition: Readonly<ModelDefinition>;
}>;

export function displayModel(name: string, model: Readonly<ModelDefinition>): string {
  return `${name} (${model.provider}/${model.id})`;
}

export function resolveModel(config: AgentsConfig, name: string): ResolvedModel {
  if (!Object.prototype.hasOwnProperty.call(config.models, name)) {
    throw new Error(
      `unknown model '${name}'; configured models: ${Object.keys(config.models).sort().join(", ")}`,
    );
  }

  return { name, definition: config.models[name]! };
}

export function resolveCouncilMembers(
  config: AgentsConfig,
  explicitMembers: readonly string[] | undefined,
  parentCwd: string,
  childCwd: string,
): readonly string[] {
  if (explicitMembers !== undefined) {
    for (const name of explicitMembers) resolveModel(config, name);
    return Object.freeze([...explicitMembers]);
  }

  const overrides = loadApplicablePolicies(parentCwd, childCwd)
    .map((policy) => policy.council)
    .filter((council): council is readonly string[] => council !== undefined);
  let selected: readonly string[];
  if (overrides.length === 0) {
    selected = config.defaults.council;
  } else {
    const first = overrides[0]!;
    if (
      overrides.some(
        (council) =>
          council.length !== first.length || council.some((name, index) => name !== first[index]),
      )
    ) {
      throw new Error("Conflicting council defaults from applicable project policies.");
    }
    selected = first;
  }

  for (const name of selected) resolveModel(config, name);
  return selected;
}

export function preflightDelegate(
  config: AgentsConfig,
  modelName: string,
  parentCwd: string,
  childCwd: string,
): ResolvedModel {
  const resolved = resolveModel(config, modelName);
  assertRouteAllowed(resolved.name, resolved.definition, parentCwd, childCwd);
  return resolved;
}

export function preflightCouncil(
  config: AgentsConfig,
  memberNames: readonly string[],
  parentCwd: string,
  childCwd: string,
): readonly ResolvedModel[] {
  if (memberNames.length < MIN_COUNCIL_MEMBERS || memberNames.length > MAX_COUNCIL_MEMBERS) {
    throw new Error(`Council requires ${MIN_COUNCIL_MEMBERS}-${MAX_COUNCIL_MEMBERS} unique members.`);
  }

  const seen = new Set<string>();
  for (const name of memberNames) {
    if (seen.has(name)) throw new Error("Council members must be unique.");
    seen.add(name);
  }

  const resolved = memberNames.map((name) => resolveModel(config, name));
  for (const model of resolved) {
    assertRouteAllowed(model.name, model.definition, parentCwd, childCwd);
  }
  return Object.freeze(resolved);
}

export function councilPerspective(model: ResolvedModel): string;
export function councilPerspective(name: string, model: Readonly<ModelDefinition>): string;
export function councilPerspective(
  modelOrName: ResolvedModel | string,
  definition?: Readonly<ModelDefinition>,
): string {
  const model = typeof modelOrName === "string" ? definition : modelOrName.definition;
  return model?.perspective?.trim() ? model.perspective : NEUTRAL_PERSPECTIVE;
}
