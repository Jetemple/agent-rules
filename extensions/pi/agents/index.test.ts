import { afterEach, describe, expect, mock, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

mock.module("@earendil-works/pi-ai", () => ({
  StringEnum: (values: readonly string[], options: Record<string, unknown> = {}) => ({
    type: "string",
    enum: [...values],
    ...options,
  }),
}));
mock.module("@earendil-works/pi-coding-agent", () => ({
  getMarkdownTheme: () => ({}),
}));
mock.module("@earendil-works/pi-tui", () => ({
  Markdown: class Markdown {},
  Text: class Text {
    text: string;
    constructor(text: string) {
      this.text = text;
    }
  },
}));
mock.module("typebox", () => ({
  Type: {
    Array: (items: unknown, options: Record<string, unknown> = {}) => ({ items, ...options }),
    Object: (properties: unknown) => properties,
    Optional: (schema: unknown) => schema,
    String: (options: Record<string, unknown> = {}) => ({ type: "string", ...options }),
  },
}));

const { createAgentsExtension } = await import("./index.js");

const roots: string[] = [];
function project(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agents-index-"));
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

function usage() {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

function fakePi() {
  const tools: any[] = [];
  const commands: Array<{ name: string; definition: any }> = [];
  const messages: string[] = [];
  return {
    tools,
    commands,
    messages,
    registerTool(tool: any) {
      tools.push(tool);
    },
    registerCommand(name: string, definition: any) {
      commands.push({ name, definition });
    },
    sendUserMessage(message: string) {
      messages.push(message);
    },
  };
}

describe("agents extension registration", () => {
  test("denied councils launch no child and publish no progress update", async () => {
    const root = project();
    policy(root, {
      version: 1,
      allowedModels: [{ provider: "provider-a", id: "model-fast" }],
    });
    const pi = fakePi();
    let spawnCalls = 0;
    let updateCalls = 0;
    createAgentsExtension({
      config,
      spawnChild: async () => {
        spawnCalls += 1;
        throw new Error("launcher should not be called");
      },
    })(pi as any);
    const council = pi.tools.find((tool) => tool.name === "council");

    await expect(
      council.execute(
        "id",
        { question: "test", members: ["fast", "careful"] },
        new AbortController().signal,
        () => {
          updateCalls += 1;
        },
        { cwd: root },
      ),
    ).rejects.toThrow("careful (provider-b/org/model-careful) is denied");
    expect(spawnCalls).toBe(0);
    expect(updateCalls).toBe(0);
  });

  test("approved councils launch every resolved route after preflight", async () => {
    const root = project();
    policy(root, {
      version: 1,
      allowedModels: [
        { provider: "provider-a", id: "model-fast" },
        { provider: "provider-b", id: "org/model-careful" },
      ],
    });
    const pi = fakePi();
    const launches: any[] = [];
    const updates: string[] = [];
    createAgentsExtension({
      config,
      spawnChild: async (options: any) => {
        launches.push(options);
        return {
          model: options.resolved.name,
          route: {
            provider: options.resolved.definition.provider,
            id: options.resolved.definition.id,
          },
          role: options.role,
          task: options.task,
          cwd: options.cwd,
          output: "approved",
          exitCode: 0,
          usage: usage(),
        };
      },
    })(pi as any);
    const council = pi.tools.find((tool) => tool.name === "council");

    const result = await council.execute(
      "id",
      { question: "test", members: ["fast", "careful"] },
      new AbortController().signal,
      (update: any) => updates.push(update.content[0].text),
      { cwd: root },
    );

    expect(launches.map((item) => item.resolved.name)).toEqual(["fast", "careful"]);
    expect(launches.map((item) => item.resolved.definition)).toEqual([
      config.models.fast,
      config.models.careful,
    ]);
    expect(launches.map((item) => item.role)).toEqual(["reviewer", "reviewer"]);
    expect(launches.find((item) => item.resolved.name === "fast").task).toContain(
      "Review independently and let the evidence determine the conclusion.",
    );
    expect(launches.find((item) => item.resolved.name === "careful").task).toContain(
      "Check long-term failure modes.",
    );
    expect(updates[0]).toContain("fast (provider-a/model-fast)");
    expect(updates[0]).toContain("careful (provider-b/org/model-careful)");
    expect(result.content[0].text).toContain("## fast (provider-a/model-fast)");
    expect(result.content[0].text).toContain("## careful (provider-b/org/model-careful)");
  });

  test("builds model schemas dynamically and labels an unresolved default preview", () => {
    const pi = fakePi();
    createAgentsExtension({ config })(pi as any);
    const delegate = pi.tools.find((tool) => tool.name === "delegate");
    const council = pi.tools.find((tool) => tool.name === "council");

    expect(delegate.parameters.model.enum).toEqual(["careful", "fast"]);
    expect(council.parameters.members.items.enum).toEqual(["careful", "fast"]);

    const preview = council.renderCall(
      { question: "test" },
      { fg: (_name: string, text: string) => text, bold: (text: string) => text },
    );
    expect(preview.text).toContain("configured scoped default");
    expect(preview.text).not.toContain("fast");
    expect(preview.text).not.toContain("careful");
  });

  test("registers one council command that delegates roster selection to runtime", async () => {
    const pi = fakePi();
    createAgentsExtension({ config })(pi as any);

    expect(pi.commands.filter((command) => command.name === "council")).toHaveLength(1);
    await pi.commands.find((command) => command.name === "council")!.definition.handler("test question", {
      ui: { notify() {} },
    });

    expect(pi.messages).toHaveLength(1);
    expect(pi.messages[0]).toContain("Use the council tool");
    expect(pi.messages[0]).not.toContain("fast");
    expect(pi.messages[0]).not.toContain("careful");
  });
});
