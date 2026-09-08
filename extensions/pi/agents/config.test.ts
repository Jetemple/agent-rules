import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  DEFAULT_AGENTS_CONFIG,
  defaultConfigPath,
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

const validDefaults = {
  scout: "good",
  reviewer: "good",
  skeptic: "good",
  council: ["good", "other"],
};

const validModels = {
  good: { provider: "p", id: "m" },
  other: { provider: "p", id: "other" },
};

describe("defaultConfigPath", () => {
  test("uses the supplied XDG config home and home", () => {
    expect(
      defaultConfigPath({ home: "/tmp/agent-home", xdgConfigHome: "/tmp/agent-config" }),
    ).toBe("/tmp/agent-config/agent-rules/pi-agents.json");
  });
});

describe("loadAgentsConfig", () => {
  test("uses public defaults only when the config file is absent", () => {
    const root = tempRoot();
    const config = loadAgentsConfig({ configPath: path.join(root, "missing.json") });

    expect(config).toEqual(DEFAULT_AGENTS_CONFIG);
    expect(config).not.toBe(DEFAULT_AGENTS_CONFIG);
    expect(Object.isFrozen(config)).toBe(true);
    expect(Object.isFrozen(config.models)).toBe(true);
    expect(Object.isFrozen(config.models.luna)).toBe(true);
    expect(Object.isFrozen(config.defaults.council)).toBe(true);
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
    expect(config.models.luna).toBeUndefined();
  });

  test("uses the injected home when expanding extension paths", () => {
    const root = tempRoot();
    const file = writeConfig(root, {
      models: {
        ...validModels,
        good: { provider: "p", id: "m", extensions: ["~/trusted.ts", "/opt/extra.ts"] },
      },
      defaults: validDefaults,
    });

    expect(loadAgentsConfig({ configPath: file, home: "/tmp/configured-home" }).models.good.extensions).toEqual([
      "/tmp/configured-home/trusted.ts",
      "/opt/extra.ts",
    ]);
  });

  test("loads the default path from the supplied homes when no path is given", () => {
    const root = tempRoot();
    const home = path.join(root, "home");
    const xdgConfigHome = path.join(root, "xdg");
    const file = defaultConfigPath({ home, xdgConfigHome });
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(
      file,
      `${JSON.stringify({ models: validModels, defaults: validDefaults }, null, 2)}\n`,
    );

    expect(loadAgentsConfig({ home, xdgConfigHome })).toEqual({
      models: validModels,
      defaults: validDefaults,
    });
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
        defaults: validDefaults,
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
    [{ models: validModels, defaults: validDefaults, extra: true }, "unknown top-level key"],
    [
      {
        models: { good: { provider: "p", id: "m", extra: true } },
        defaults: validDefaults,
      },
      "unknown model key",
    ],
    [
      { models: { good: { provider: "", id: "m" } }, defaults: validDefaults },
      "provider must be a non-empty string",
    ],
    [
      { models: { good: { provider: "p", id: "   " } }, defaults: validDefaults },
      "id must be a non-empty string",
    ],
    [
      {
        models: validModels,
        defaults: { ...validDefaults, council: ["good", "good"] },
      },
      "duplicate council member",
    ],
    [
      {
        models: validModels,
        defaults: { ...validDefaults, council: ["good"] },
      },
      "council must contain 2 to 5 models",
    ],
    [
      {
        models: {
          one: { provider: "p", id: "1" },
          two: { provider: "p", id: "2" },
          three: { provider: "p", id: "3" },
          four: { provider: "p", id: "4" },
          five: { provider: "p", id: "5" },
          six: { provider: "p", id: "6" },
        },
        defaults: { scout: "one", reviewer: "one", skeptic: "one", council: ["one", "two", "three", "four", "five", "six"] },
      },
      "council must contain 2 to 5 models",
    ],
    [
      { models: validModels, defaults: { scout: "good", reviewer: "good", skeptic: "good" } },
      "missing default key 'council'",
    ],
    [
      {
        models: {
          ...validModels,
          good: { provider: "p", id: "m", perspective: 42 },
        },
        defaults: validDefaults,
      },
      "perspective must be a string",
    ],
    [
      {
        models: validModels,
        defaults: { scout: "toString", reviewer: "good", skeptic: "good", council: ["good", "other"] },
      },
      "unknown model 'toString'",
    ],
    [
      { models: validModels, defaults: { ...validDefaults, extra: "good" } },
      "unknown default key",
    ],
    [null, "configuration must be an object"],
  ] as const)("rejects invalid configuration %#", (value, message) => {
    const file = writeConfig(tempRoot(), value);
    expect(() => loadAgentsConfig({ configPath: file })).toThrow(message);
  });

  test("rejects a non-array model extension item", () => {
    const file = writeConfig(tempRoot(), {
      models: { good: { provider: "p", id: "m", extensions: ["   "] } },
      defaults: validDefaults,
    });

    expect(() => loadAgentsConfig({ configPath: file })).toThrow("extensions must contain non-empty strings");
  });
});
