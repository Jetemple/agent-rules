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

const TOP_LEVEL_KEYS = new Set(["models", "defaults"]);
const MODEL_KEYS = new Set(["provider", "id", "extensions", "perspective"]);
const DEFAULT_KEYS = new Set(["scout", "reviewer", "skeptic", "council"]);
const MODEL_NAME = /^[a-z][a-z0-9-]{0,31}$/;

export type ConfigPathOptions = Readonly<{
  home?: string;
  xdgConfigHome?: string;
}>;

export type LoadAgentsConfigOptions = ConfigPathOptions &
  Readonly<{
    configPath?: string;
  }>;

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function configLabel(configPath: string): string {
  return path.basename(configPath) || "pi-agents.json";
}

function invalid(configPath: string, location: string, message: string): never {
  throw new Error(`${configLabel(configPath)}: ${location} ${message}`);
}

function assertKeys(
  value: UnknownRecord,
  allowed: ReadonlySet<string>,
  configPath: string,
  location: string,
  keyKind: string,
): void {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) invalid(configPath, location, `unknown ${keyKind} '${key}'`);
  }
}

function requireRecord(value: unknown, configPath: string, location: string): UnknownRecord {
  if (!isRecord(value)) invalid(configPath, location, "must be an object");
  return value;
}

function hasModel(models: Readonly<Record<string, ModelDefinition>>, name: string): boolean {
  return Object.prototype.hasOwnProperty.call(models, name);
}

function freezeConfig(
  models: Readonly<Record<string, Readonly<ModelDefinition>>>,
  defaults: Readonly<{
    scout: string;
    reviewer: string;
    skeptic: string;
    council: readonly string[];
  }>,
): AgentsConfig {
  const frozenModels: Record<string, Readonly<ModelDefinition>> = {};
  for (const [name, model] of Object.entries(models)) {
    const definition: ModelDefinition = {
      provider: model.provider,
      id: model.id,
    };
    if (model.extensions !== undefined) definition.extensions = [...model.extensions];
    if (model.perspective !== undefined) definition.perspective = model.perspective;
    if (definition.extensions !== undefined) Object.freeze(definition.extensions);
    frozenModels[name] = Object.freeze(definition);
  }

  return Object.freeze({
    models: Object.freeze(frozenModels),
    defaults: Object.freeze({
      scout: defaults.scout,
      reviewer: defaults.reviewer,
      skeptic: defaults.skeptic,
      council: Object.freeze([...defaults.council]),
    }),
  });
}

function expandHome(filePath: string, home: string): string {
  if (filePath === "~") return home;
  if (filePath.startsWith("~/")) return path.join(home, filePath.slice(2));
  return filePath;
}

export function defaultConfigPath(options: ConfigPathOptions = {}): string {
  const home = options.home ?? os.homedir();
  const xdgConfigHome = options.xdgConfigHome || process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdgConfigHome, "agent-rules", "pi-agents.json");
}

function parseConfig(value: unknown, configPath: string, home: string): AgentsConfig {
  const root = requireRecord(value, configPath, "configuration");
  assertKeys(root, TOP_LEVEL_KEYS, configPath, "configuration", "top-level key");

  const rawModels = requireRecord(root.models, configPath, "models");
  const modelNames = Object.keys(rawModels);
  if (modelNames.length === 0) invalid(configPath, "models", "must contain at least one model");

  const models: Record<string, ModelDefinition> = {};
  for (const name of modelNames) {
    if (!MODEL_NAME.test(name)) invalid(configPath, `models.${name}`, "has an invalid model name");

    const rawModel = requireRecord(rawModels[name], configPath, `models.${name}`);
    assertKeys(rawModel, MODEL_KEYS, configPath, `models.${name}`, "model key");

    if (typeof rawModel.provider !== "string" || rawModel.provider.trim() === "") {
      invalid(configPath, `models.${name}.provider`, "must be a non-empty string");
    }
    if (typeof rawModel.id !== "string" || rawModel.id.trim() === "") {
      invalid(configPath, `models.${name}.id`, "must be a non-empty string");
    }

    const model: ModelDefinition = {
      provider: rawModel.provider,
      id: rawModel.id,
    };

    if (rawModel.extensions !== undefined) {
      if (!Array.isArray(rawModel.extensions)) {
        invalid(configPath, `models.${name}.extensions`, "must be an array");
      }
      const extensions: string[] = [];
      for (const extension of rawModel.extensions) {
        if (typeof extension !== "string" || extension.trim() === "") {
          invalid(configPath, `models.${name}.extensions`, "must contain non-empty strings");
        }
        extensions.push(expandHome(extension, home));
      }
      model.extensions = extensions;
    }

    if (rawModel.perspective !== undefined) {
      if (typeof rawModel.perspective !== "string") {
        invalid(configPath, `models.${name}.perspective`, "must be a string");
      }
      model.perspective = rawModel.perspective;
    }

    models[name] = model;
  }

  const rawDefaults = requireRecord(root.defaults, configPath, "defaults");
  assertKeys(rawDefaults, DEFAULT_KEYS, configPath, "defaults", "default key");
  for (const key of ["scout", "reviewer", "skeptic", "council"] as const) {
    if (!(key in rawDefaults)) invalid(configPath, "defaults", `missing default key '${key}'`);
  }

  const defaults: {
    scout: string;
    reviewer: string;
    skeptic: string;
    council: string[];
  } = {
    scout: "",
    reviewer: "",
    skeptic: "",
    council: [],
  };

  for (const role of ["scout", "reviewer", "skeptic"] as const) {
    const modelName = rawDefaults[role];
    if (typeof modelName !== "string") invalid(configPath, `defaults.${role}`, "must be a string");
    if (!hasModel(models, modelName)) invalid(configPath, `defaults.${role}`, `references unknown model '${modelName}'`);
    defaults[role] = modelName;
  }

  if (!Array.isArray(rawDefaults.council) || rawDefaults.council.length < 2 || rawDefaults.council.length > 5) {
    invalid(configPath, "defaults.council", "must contain 2 to 5 models");
  }

  const seen = new Set<string>();
  for (const modelName of rawDefaults.council) {
    if (typeof modelName !== "string") invalid(configPath, "defaults.council", "must contain model names");
    if (seen.has(modelName)) invalid(configPath, "defaults.council", `contains duplicate council member '${modelName}'`);
    if (!hasModel(models, modelName)) invalid(configPath, "defaults.council", `references unknown model '${modelName}'`);
    seen.add(modelName);
    defaults.council.push(modelName);
  }

  return freezeConfig(models, defaults);
}

export function loadAgentsConfig(options: LoadAgentsConfigOptions = {}): AgentsConfig {
  const configPath = options.configPath ?? defaultConfigPath(options);
  const home = options.home ?? os.homedir();

  let source: string;
  try {
    source = fs.readFileSync(configPath, "utf8");
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return freezeConfig(DEFAULT_AGENTS_CONFIG.models, DEFAULT_AGENTS_CONFIG.defaults);
    }
    throw new Error(`${configLabel(configPath)}: unable to read configuration`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(source);
  } catch {
    throw new Error(`${configLabel(configPath)}: invalid JSON`);
  }

  return parseConfig(parsed, configPath, home);
}
