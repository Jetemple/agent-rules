import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  councilPerspective,
  displayModel,
  preflightCouncil,
  preflightDelegate,
  resolveCouncilMembers,
  resolveModel,
} from "./runtime.js";

const roots: string[] = [];
function project(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agents-runtime-"));
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

const fiveModelConfig = {
  models: {
    ...config.models,
    third: { provider: "provider-c", id: "model-third" },
    fourth: { provider: "provider-d", id: "model-fourth" },
    fifth: { provider: "provider-e", id: "model-fifth" },
  },
  defaults: {
    ...config.defaults,
    council: ["fast", "careful", "third", "fourth", "fifth"],
  },
} as const;

describe("runtime model resolution", () => {
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

  test("resolves configured role defaults without hardcoded aliases", () => {
    const root = project();

    expect(preflightDelegate(config, config.defaults.scout, root, root).name).toBe("fast");
    expect(preflightDelegate(config, config.defaults.reviewer, root, root).name).toBe("careful");
  });

  test("uses configured perspectives and a neutral fallback", () => {
    expect(councilPerspective("careful", config.models.careful)).toBe(
      "Check long-term failure modes.",
    );
    expect(councilPerspective("fast", config.models.fast)).toBe(
      "Review independently and let the evidence determine the conclusion.",
    );
    expect(
      councilPerspective("spaced", {
        provider: "provider-c",
        id: "model-spaced",
        perspective: "  Preserve this spacing.  ",
      }),
    ).toBe("  Preserve this spacing.  ");
    expect(
      councilPerspective("blank", {
        provider: "provider-c",
        id: "model-blank",
        perspective: "   ",
      }),
    ).toBe("Review independently and let the evidence determine the conclusion.");
  });

  test("uses the global configured council when no policy supplies an override", () => {
    const root = project();

    expect(resolveCouncilMembers(config, undefined, root, root)).toEqual(["fast", "careful"]);
  });

  test("uses a scoped override from either the parent or child cwd", () => {
    const protectedParent = project();
    const outsideChild = project();
    policy(protectedParent, {
      version: 1,
      allowedModels: [],
      council: ["fast", "careful"],
    });
    expect(resolveCouncilMembers(config, undefined, protectedParent, outsideChild)).toEqual([
      "fast",
      "careful",
    ]);

    const outsideParent = project();
    const protectedChild = project();
    policy(protectedChild, {
      version: 1,
      allowedModels: [],
      council: ["careful", "fast"],
    });
    expect(resolveCouncilMembers(config, undefined, outsideParent, protectedChild)).toEqual([
      "careful",
      "fast",
    ]);
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

    expect(resolveCouncilMembers(config, ["careful", "fast"], root, root)).toEqual([
      "careful",
      "fast",
    ]);
  });

  test("rejects an unknown model in a scoped roster during catalog resolution", () => {
    const root = project();
    policy(root, { version: 1, allowedModels: [], council: ["fast", "missing"] });

    expect(() => resolveCouncilMembers(config, undefined, root, root)).toThrow(
      "unknown model 'missing'; configured models: careful, fast",
    );
  });

  test("preflights every council member before returning any launch", () => {
    const root = project();
    policy(root, {
      version: 1,
      allowedModels: [{ provider: "provider-a", id: "model-fast" }],
    });

    expect(() => preflightCouncil(config, ["fast", "careful"], root, root)).toThrow(
      "careful (provider-b/org/model-careful) is denied",
    );
  });

  test("rejects council rosters outside the supported size range", () => {
    const root = project();

    expect(() => preflightCouncil(config, ["fast"], root, root)).toThrow("2-5");
    expect(() =>
      preflightCouncil(
        fiveModelConfig,
        ["fast", "careful", "third", "fourth", "fifth", "sixth"],
        root,
        root,
      ),
    ).toThrow("2-5");
  });

  test("accepts councils with two through five unique configured members", () => {
    const root = project();

    expect(preflightCouncil(config, ["fast", "careful"], root, root).map((model) => model.name)).toEqual([
      "fast",
      "careful",
    ]);
    expect(
      preflightCouncil(
        fiveModelConfig,
        ["fast", "careful", "third", "fourth", "fifth"],
        root,
        root,
      ).map((model) => model.name),
    ).toEqual(["fast", "careful", "third", "fourth", "fifth"]);
  });

  test("rejects duplicate requested council members", () => {
    const root = project();

    expect(() => preflightCouncil(config, ["fast", "fast"], root, root)).toThrow(/unique/i);
  });

  test("returns the exact resolved model definition", () => {
    expect(resolveModel(config, "careful")).toEqual({
      name: "careful",
      definition: config.models.careful,
    });
  });
});
