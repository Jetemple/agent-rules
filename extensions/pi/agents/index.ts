import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import { Markdown, Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const MODEL_ALIASES = ["luna", "terra", "sol", "opus", "sonnet"] as const;
const ROLES = ["scout", "reviewer", "skeptic"] as const;

type ModelAlias = (typeof MODEL_ALIASES)[number];
type ModelConfig = {
  provider: string;
  id: string;
  extensions?: string[];
};

const DEFAULT_MODEL_CONFIGS: Record<ModelAlias, ModelConfig> = {
  luna: { provider: "openai-codex", id: "gpt-5.6-luna" },
  terra: { provider: "openai-codex", id: "gpt-5.6-terra" },
  sol: { provider: "openai-codex", id: "gpt-5.6-sol" },
  opus: { provider: "anthropic", id: "claude-opus-5" },
  sonnet: { provider: "anthropic", id: "claude-sonnet-5" },
};

function expandHome(filePath: string): string {
  if (filePath === "~") return os.homedir();
  if (filePath.startsWith("~/")) return path.join(os.homedir(), filePath.slice(2));
  return filePath;
}

function loadModelConfigs(): Record<ModelAlias, ModelConfig> {
  const configPath = expandHome(
    process.env.PI_AGENTS_CONFIG ??
      path.join(process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), ".config"), "agent-rules", "pi-agents.json"),
  );
  if (!fs.existsSync(configPath)) return DEFAULT_MODEL_CONFIGS;

  const parsed = JSON.parse(fs.readFileSync(configPath, "utf8")) as { models?: Record<string, unknown> };
  if (!parsed.models || typeof parsed.models !== "object") {
    throw new Error(`${configPath}: expected a top-level \"models\" object`);
  }

  const configs = { ...DEFAULT_MODEL_CONFIGS };
  for (const alias of MODEL_ALIASES) {
    const candidate = parsed.models[alias];
    if (candidate === undefined) continue;
    if (!candidate || typeof candidate !== "object") {
      throw new Error(`${configPath}: models.${alias} must be an object`);
    }
    const value = candidate as Record<string, unknown>;
    if (typeof value.provider !== "string" || !value.provider || typeof value.id !== "string" || !value.id) {
      throw new Error(`${configPath}: models.${alias} requires non-empty provider and id strings`);
    }
    if (value.extensions !== undefined && (!Array.isArray(value.extensions) || value.extensions.some((item) => typeof item !== "string"))) {
      throw new Error(`${configPath}: models.${alias}.extensions must be an array of paths`);
    }
    configs[alias] = {
      provider: value.provider,
      id: value.id,
      extensions: (value.extensions as string[] | undefined)?.map(expandHome),
    };
  }
  return configs;
}

const MODEL_CONFIGS = loadModelConfigs();
const THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;
const DEFAULT_COUNCIL = ["luna", "sol", "opus", "sonnet"] as const;
const MAX_COUNCIL_MEMBERS = 5;
const MAX_CONCURRENCY = 2;
const OUTPUT_CAP_BYTES = 12 * 1024;
const COUNCIL_OUTPUT_CAP_BYTES = 48 * 1024;
const STDERR_CAP_BYTES = 8 * 1024;
const MAX_USAGE_VALUE = 1_000_000_000_000;
const CHILD_TIMEOUT_MS = 5 * 60 * 1000;
const MAX_EVENT_LINE_BYTES = 2 * 1024 * 1024;
const EXTENSION_DIR = path.dirname(fileURLToPath(import.meta.url));
const CHILD_GUARD_PATH = path.join(EXTENSION_DIR, "child-guard.ts");
type Role = (typeof ROLES)[number];
type ThinkingLevel = (typeof THINKING_LEVELS)[number];

function defaultThinking(model: ModelAlias, role: Role): ThinkingLevel {
  if (model === "luna" || model === "terra") return "max";
  return role === "scout" ? "medium" : "high";
}

type Usage = {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  totalTokens: number;
  cost: {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
    total: number;
  };
};

type RunResult = {
  model: ModelAlias;
  role: Role;
  task: string;
  cwd: string;
  output: string;
  error?: string;
  stopReason?: string;
  exitCode: number;
  usage: Usage;
};

type AgentDetails = {
  kind: "delegate" | "council";
  results: RunResult[];
};

function emptyUsage(): Usage {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

function safeUsageNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= MAX_USAGE_VALUE ? value : 0;
}

function addUsageValue(current: number, incoming: unknown): number {
  return Math.min(MAX_USAGE_VALUE, current + safeUsageNumber(incoming));
}

function addUsage(total: Usage, usage: unknown): void {
  if (!usage || typeof usage !== "object") return;
  const value = usage as Record<string, unknown>;
  const cost = value.cost && typeof value.cost === "object" ? (value.cost as Record<string, unknown>) : {};
  total.input = addUsageValue(total.input, value.input);
  total.output = addUsageValue(total.output, value.output);
  total.cacheRead = addUsageValue(total.cacheRead, value.cacheRead);
  total.cacheWrite = addUsageValue(total.cacheWrite, value.cacheWrite);
  total.totalTokens = addUsageValue(total.totalTokens, value.totalTokens);
  total.cost.input = addUsageValue(total.cost.input, cost.input);
  total.cost.output = addUsageValue(total.cost.output, cost.output);
  total.cost.cacheRead = addUsageValue(total.cost.cacheRead, cost.cacheRead);
  total.cost.cacheWrite = addUsageValue(total.cost.cacheWrite, cost.cacheWrite);
  total.cost.total = addUsageValue(total.cost.total, cost.total);
}

function aggregateUsage(results: RunResult[]): Usage {
  const total = emptyUsage();
  for (const result of results) addUsage(total, result.usage);
  return total;
}

function truncateUtf8(text: string, maxBytes: number): string {
  if (Buffer.byteLength(text, "utf8") <= maxBytes) return text;

  const notice = "\n\n[Output capped.]";
  const contentLimit = Math.max(0, maxBytes - Buffer.byteLength(notice, "utf8"));
  let truncated = Buffer.from(text, "utf8").subarray(0, contentLimit).toString("utf8");
  truncated = truncated.replace(/\uFFFD+$/, "");
  return truncated + notice;
}

function formatTokens(value: number): string {
  if (value < 1_000) return `${value}`;
  if (value < 10_000) return `${(value / 1_000).toFixed(1)}k`;
  if (value < 1_000_000) return `${Math.round(value / 1_000)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

function formatUsage(usage: Usage): string {
  const parts = [`↑${formatTokens(usage.input)}`, `↓${formatTokens(usage.output)}`];
  if (usage.cost.total > 0) parts.push(`~$${usage.cost.total.toFixed(3)}`);
  return parts.join(" ");
}

function getPiInvocation(args: string[]): { command: string; args: string[] } {
  const currentScript = process.argv[1];
  const isBunVirtualScript = currentScript?.startsWith("/$bunfs/root/");
  if (currentScript && !isBunVirtualScript && fs.existsSync(currentScript)) {
    return { command: process.execPath, args: [currentScript, ...args] };
  }

  const executable = path.basename(process.execPath).toLowerCase();
  if (!/^(node|bun)(\.exe)?$/.test(executable)) return { command: process.execPath, args };
  return { command: "pi", args };
}

function resolveCwd(requested: string | undefined, fallback: string): string {
  const resolved = path.resolve(fallback, requested ?? ".");
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
    throw new Error(`Agent cwd is not a directory: ${resolved}`);
  }
  return resolved;
}

function rolePrompt(role: Role, model: ModelAlias): string {
  const shared = [
    "You are a bounded, read-only child agent with an isolated context.",
    "Never modify files, run shell commands, inspect credentials, access paths outside the working directory, or contact remote services.",
    "Use only the provided read-only tools. Read local AGENTS.md or CLAUDE.md first when relevant.",
    "Return evidence, exact file:line citations, uncertainties, and a concise conclusion.",
    "Keep the final answer under 120 lines. Do not include large code excerpts or full diffs.",
  ].join("\n");

  const specific: Record<Role, string> = {
    scout:
      "Act as a fast codebase scout. Locate the smallest relevant file set, map how it connects, and return compressed findings for the main agent.",
    reviewer:
      "Act as an independent senior reviewer. Be skeptical, verify claims against files, prioritize correctness and security, and give a ship verdict.",
    skeptic:
      "Act as a pragmatic dissenting reviewer. Search for assumptions, missing alternatives, edge cases, and unnecessary complexity. Do not agree merely to form consensus.",
  };

  return `${shared}\n\n${specific[role]}\nYou are the ${model.toUpperCase()} council member.`;
}

function councilPerspective(model: ModelAlias): string {
  switch (model) {
    case "luna":
      return "Prioritize fast falsification: identify obvious defects, unsupported claims, and the cheapest adequate solution.";
    case "terra":
      return "Prioritize pragmatic engineering tradeoffs, maintainability, and a viable alternative to the leading proposal.";
    case "sol":
      return "Perform a deep review: trace subtle failure modes, security concerns, and long-term design consequences.";
    case "opus":
      return "Challenge load-bearing assumptions, identify subtle systemic risks, and develop the strongest competing recommendation.";
    case "sonnet":
      return "Prioritize balanced implementation feasibility, code quality, and a clear recommendation grounded in the available evidence.";
  }
}

async function runChild(options: {
  model: ModelAlias;
  role: Role;
  thinking: ThinkingLevel;
  task: string;
  cwd: string;
  signal?: AbortSignal;
}): Promise<RunResult> {
  if (options.signal?.aborted) {
    return {
      model: options.model,
      role: options.role,
      task: options.task,
      cwd: options.cwd,
      output: "(not started)",
      error: "Aborted before start",
      stopReason: "aborted",
      exitCode: 1,
      usage: emptyUsage(),
    };
  }

  const usage = emptyUsage();
  let output = "";
  let stderr = "";
  let stopReason: string | undefined;
  let errorMessage: string | undefined;
  let timedOut = false;
  let protocolError = false;
  let terminalMessageSeen = false;

  const model = MODEL_CONFIGS[options.model];
  const args = [
    "--mode",
    "json",
    "-p",
    "--no-session",
    "--no-extensions",
    "-e",
    CHILD_GUARD_PATH,
    ...(model.extensions ?? []).flatMap((extensionPath) => ["-e", extensionPath]),
    "--no-skills",
    "--no-prompt-templates",
    "--no-context-files",
    "--provider",
    model.provider,
    "--model",
    model.id,
    "--models",
    `${model.provider}/${model.id}`,
    "--thinking",
    options.thinking,
    "--tools",
    "safe_read,safe_grep,safe_find",
    "--append-system-prompt",
    rolePrompt(options.role, options.model),
    `Task:\n${options.task}`,
  ];

  const invocation = getPiInvocation(args);
  const exitCode = await new Promise<number>((resolve) => {
    const useProcessGroup = process.platform !== "win32";
    const child = spawn(invocation.command, invocation.args, {
      cwd: options.cwd,
      shell: false,
      detached: useProcessGroup,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdoutBuffer = "";
    const stdoutDecoder = new StringDecoder("utf8");
    let closed = false;
    let settled = false;
    let terminating = false;
    let killTimer: NodeJS.Timeout | undefined;
    let forceSettleTimer: NodeJS.Timeout | undefined;
    let requestTimeout: NodeJS.Timeout | undefined;

    const killTree = (signal: NodeJS.Signals) => {
      try {
        if (useProcessGroup && child.pid) process.kill(-child.pid, signal);
        else child.kill(signal);
      } catch {
        // The process may already have exited.
      }
    };

    const abortHandler = () => terminate();
    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      if (requestTimeout) clearTimeout(requestTimeout);
      if (killTimer) clearTimeout(killTimer);
      if (forceSettleTimer) clearTimeout(forceSettleTimer);
      options.signal?.removeEventListener("abort", abortHandler);
      resolve(code);
    };

    const terminate = () => {
      if (closed || settled || terminating) return;
      terminating = true;
      killTree("SIGTERM");
      killTimer = setTimeout(() => {
        if (!closed) killTree("SIGKILL");
      }, 5_000);
      forceSettleTimer = setTimeout(() => {
        if (!closed) {
          errorMessage ??= "Child did not exit after forced termination";
          finish(1);
        }
      }, 7_000);
    };

    const processLine = (line: string) => {
      if (!line.trim()) return;
      if (Buffer.byteLength(line, "utf8") > MAX_EVENT_LINE_BYTES) {
        protocolError = true;
        errorMessage = `Child emitted an oversized JSON event (>${MAX_EVENT_LINE_BYTES} bytes)`;
        stdoutBuffer = "";
        child.stdout.pause();
        child.stdout.removeAllListeners("data");
        terminate();
        return;
      }

      let event: any;
      try {
        event = JSON.parse(line);
      } catch {
        protocolError = true;
        errorMessage = "Child emitted malformed JSON output";
        stdoutBuffer = "";
        child.stdout.pause();
        child.stdout.removeAllListeners("data");
        terminate();
        return;
      }

      if (!event || typeof event !== "object" || typeof event.type !== "string") {
        protocolError = true;
        errorMessage = "Child emitted an invalid JSON event";
        stdoutBuffer = "";
        child.stdout.pause();
        child.stdout.removeAllListeners("data");
        terminate();
        return;
      }
      if (event.type !== "message_end") return;
      if (!event.message || typeof event.message !== "object" || typeof event.message.role !== "string") {
        protocolError = true;
        errorMessage = "Child emitted an invalid message_end event";
        terminate();
        return;
      }
      if (event.message.role !== "assistant") return;
      if (
        !Array.isArray(event.message.content) ||
        typeof event.message.stopReason !== "string" ||
        event.message.content.some(
          (part: any) =>
            !part ||
            typeof part !== "object" ||
            typeof part.type !== "string" ||
            (part.type === "text" && typeof part.text !== "string"),
        )
      ) {
        protocolError = true;
        errorMessage = "Child emitted an invalid assistant message";
        terminate();
        return;
      }
      const message = event.message;
      addUsage(usage, message.usage);
      stopReason = message.stopReason ?? stopReason;
      if (typeof message.errorMessage === "string") {
        errorMessage = truncateUtf8(message.errorMessage, OUTPUT_CAP_BYTES);
      }
      const texts = message.content
        .filter((part: any) => part && typeof part === "object" && part.type === "text" && typeof part.text === "string")
        .map((part: any) => part.text);
      const terminal = message.stopReason === "stop" || message.stopReason === "length";
      terminalMessageSeen = terminal && texts.length > 0;
      if (terminalMessageSeen) output = truncateUtf8(texts.join("\n"), OUTPUT_CAP_BYTES);
    };

    if (options.signal?.aborted) terminate();
    else options.signal?.addEventListener("abort", abortHandler, { once: true });

    requestTimeout = setTimeout(() => {
      timedOut = true;
      terminate();
    }, CHILD_TIMEOUT_MS);

    child.stdout.on("data", (chunk) => {
      stdoutBuffer += stdoutDecoder.write(chunk);
      const lines = stdoutBuffer.split("\n");
      stdoutBuffer = lines.pop() ?? "";
      for (const line of lines) processLine(line);
      if (Buffer.byteLength(stdoutBuffer, "utf8") > MAX_EVENT_LINE_BYTES) {
        protocolError = true;
        errorMessage = `Child buffered an oversized JSON event (>${MAX_EVENT_LINE_BYTES} bytes)`;
        stdoutBuffer = "";
        child.stdout.pause();
        child.stdout.removeAllListeners("data");
        terminate();
      }
    });

    child.stderr.on("data", (chunk) => {
      stderr = truncateUtf8(stderr + chunk.toString(), STDERR_CAP_BYTES);
    });

    child.on("error", (error) => {
      errorMessage = truncateUtf8(error.message, OUTPUT_CAP_BYTES);
      finish(1);
    });

    child.on("close", (code) => {
      if (terminating && useProcessGroup) killTree("SIGKILL");
      closed = true;
      stdoutBuffer += stdoutDecoder.end();
      if (stdoutBuffer.trim()) processLine(stdoutBuffer);
      finish(code ?? 1);
    });
  });

  const aborted = options.signal?.aborted;
  const missingFinalMessage = !terminalMessageSeen || !output.trim();
  if (missingFinalMessage) errorMessage ??= "Child produced no valid final assistant message";
  const failed =
    exitCode !== 0 ||
    stopReason === "error" ||
    stopReason === "aborted" ||
    timedOut ||
    aborted ||
    protocolError ||
    missingFinalMessage;
  const error = failed
    ? timedOut
      ? `Timed out after ${CHILD_TIMEOUT_MS / 60_000} minutes`
      : aborted
        ? "Aborted by parent"
        : errorMessage || stderr.trim() || `Child exited with code ${exitCode}`
    : undefined;

  return {
    model: options.model,
    role: options.role,
    task: options.task,
    cwd: options.cwd,
    output: truncateUtf8(output || "(no output)", OUTPUT_CAP_BYTES),
    error: error ? truncateUtf8(error, OUTPUT_CAP_BYTES) : undefined,
    stopReason,
    exitCode,
    usage,
  };
}

async function mapWithLimit<T, R>(items: T[], limit: number, fn: (item: T, index: number) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const index = next++;
      if (index >= items.length) return;
      results[index] = await fn(items[index]!, index);
    }
  });
  await Promise.all(workers);
  return results;
}

function resultText(result: RunResult): string {
  if (result.error) return truncateUtf8(`**Failed:** ${result.error}\n\n${result.output}`, OUTPUT_CAP_BYTES);
  return result.output;
}

function renderResult(result: any, expanded: boolean, theme: any) {
  const block = result.content?.find((part: any) => part.type === "text");
  const text = block?.text ?? "(no output)";
  if (expanded) return new Markdown(text, 0, 0, getMarkdownTheme());

  const lines = text.split("\n");
  const preview = lines.slice(0, 10).join("\n");
  const suffix = lines.length > 10 ? `\n${theme.fg("muted", "… Ctrl+O to expand")}` : "";
  return new Text(preview + suffix, 0, 0);
}

const CwdField = Type.Optional(
  Type.String({ maxLength: 4_096, description: "Child working directory; defaults to the current directory" }),
);

const DelegateParams = Type.Object({
  task: Type.String({ maxLength: 20_000, description: "One bounded task for the child agent" }),
  role: Type.Optional(StringEnum(ROLES, { description: "Default: reviewer" })),
  model: Type.Optional(StringEnum(MODEL_ALIASES, { description: "Default: luna for scout, sol otherwise" })),
  thinking: Type.Optional(StringEnum(THINKING_LEVELS, { description: "Default: max for luna/terra; medium for other scouts, high otherwise" })),
  cwd: CwdField,
});

const CouncilParams = Type.Object({
  question: Type.String({
    maxLength: 20_000,
    description: "The same decision or review question sent independently to every member",
  }),
  members: Type.Optional(
    Type.Array(StringEnum(MODEL_ALIASES), {
      description: "Council members; default: luna, sol, opus, and sonnet",
      minItems: 2,
      maxItems: MAX_COUNCIL_MEMBERS,
      uniqueItems: true,
    }),
  ),
  thinking: Type.Optional(StringEnum(THINKING_LEVELS, { description: "Default: max for luna/terra; high for other council members" })),
  cwd: CwdField,
});

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "delegate",
    label: "Delegate",
    description: "Run one bounded, read-only subagent in an isolated Pi process. Use for scouting or an independent review.",
    promptSnippet: "Delegate one bounded read-only scouting or review task to an isolated GPT child agent",
    promptGuidelines: [
      "Use delegate for a single independent scouting or review task when isolation materially saves main-context budget.",
      "Keep delegate tasks narrow, state the exact scope and output contract, and never delegate final edits or user decisions.",
    ],
    parameters: DelegateParams,
    async execute(_id, params, signal, onUpdate, ctx) {
      const role: Role = params.role ?? "reviewer";
      const model: ModelAlias = params.model ?? (role === "scout" ? "luna" : "sol");
      const thinking: ThinkingLevel = params.thinking ?? defaultThinking(model, role);
      const cwd = resolveCwd(params.cwd, ctx.cwd);

      onUpdate?.({ content: [{ type: "text", text: `Running ${model} ${role}…` }], details: { kind: "delegate", results: [] } });
      const result = await runChild({ model, role, thinking, task: params.task, cwd, signal });
      const content = truncateUtf8(
        `## ${model.toUpperCase()} ${role}\n\n${resultText(result)}\n\n_${formatUsage(result.usage)}_`,
        OUTPUT_CAP_BYTES,
      );
      return {
        content: [{ type: "text", text: content }],
        details: { kind: "delegate", results: [result] } satisfies AgentDetails,
        usage: result.usage,
      };
    },
    renderCall(args, theme) {
      const role = args.role ?? "reviewer";
      const model = args.model ?? (role === "scout" ? "luna" : "sol");
      const preview = args.task.length > 80 ? `${args.task.slice(0, 80)}…` : args.task;
      return new Text(
        `${theme.fg("toolTitle", theme.bold("delegate "))}${theme.fg("accent", `${model}/${role}`)}\n${theme.fg("dim", preview)}`,
        0,
        0,
      );
    },
    renderResult(result, { expanded }, theme) {
      return renderResult(result, expanded, theme);
    },
  });

  pi.registerTool({
    name: "council",
    label: "Council",
    description: "Ask two to five independent reviewers the same question in parallel, preserving disagreements for the main agent to synthesize.",
    promptSnippet: "Convene a bounded read-only GPT council for decisions that benefit from independent perspectives",
    promptGuidelines: [
      "Use council only when independent perspectives materially reduce uncertainty; the default roster is luna, sol, opus, and sonnet.",
      "After council returns, compare evidence and disagreements instead of treating majority opinion as truth.",
    ],
    parameters: CouncilParams,
    async execute(_id, params, signal, onUpdate, ctx) {
      const members = [...new Set<ModelAlias>((params.members ?? [...DEFAULT_COUNCIL]) as ModelAlias[])];
      if (members.length < 2 || members.length > MAX_COUNCIL_MEMBERS) {
        throw new Error(`Council requires 2-${MAX_COUNCIL_MEMBERS} unique members.`);
      }

      const thinking: ThinkingLevel = params.thinking ?? "high";
      const cwd = resolveCwd(params.cwd, ctx.cwd);
      const completed: RunResult[] = [];
      onUpdate?.({
        content: [{ type: "text", text: `Council running: ${members.join(", ")}…` }],
        details: { kind: "council", results: [] },
      });

      const results = await mapWithLimit(members, MAX_CONCURRENCY, async (model) => {
        const task = [
          params.question,
          "",
          councilPerspective(model),
          "Review independently. Do not infer or imitate what other council members might say.",
        ].join("\n");
        const role: Role = model === "terra" ? "skeptic" : "reviewer";
        const childThinking = params.thinking ?? defaultThinking(model, role);
        const result = await runChild({ model, role, thinking: childThinking, task, cwd, signal });
        completed.push(result);
        onUpdate?.({
          content: [{ type: "text", text: `Council: ${completed.length}/${members.length} complete…` }],
          details: { kind: "council", results: [...completed] },
        });
        return result;
      });

      const sections = results.map(
        (result) => `## ${result.model.toUpperCase()}\n\n${resultText(result)}\n\n_${formatUsage(result.usage)}_`,
      );
      const content = truncateUtf8(
        [
          "# Council reports",
          ...sections,
          "## Synthesis contract",
          "Compare the cited evidence, surface disagreements and uncertainty, reject unsupported consensus, and make the final recommendation in the main-agent response.",
        ].join("\n\n"),
        COUNCIL_OUTPUT_CAP_BYTES,
      );

      return {
        content: [{ type: "text", text: content }],
        details: { kind: "council", results } satisfies AgentDetails,
        usage: aggregateUsage(results),
      };
    },
    renderCall(args, theme) {
      const members = args.members ?? DEFAULT_COUNCIL;
      const preview = args.question.length > 80 ? `${args.question.slice(0, 80)}…` : args.question;
      return new Text(
        `${theme.fg("toolTitle", theme.bold("council "))}${theme.fg("accent", members.join(" + "))}\n${theme.fg("dim", preview)}`,
        0,
        0,
      );
    },
    renderResult(result, { expanded }, theme) {
      return renderResult(result, expanded, theme);
    },
  });

  pi.registerCommand("delegate", {
    description: "Delegate a bounded read-only task to a child agent",
    handler: async (args, ctx) => {
      if (!args.trim()) {
        ctx.ui.notify("Usage: /delegate <bounded task>", "info");
        return;
      }
      pi.sendUserMessage(`Use the delegate tool for this bounded read-only task:\n\n${args}`);
    },
  });

  pi.registerCommand("council", {
    description: "Convene the configured default model council for independent review",
    handler: async (args, ctx) => {
      if (!args.trim()) {
        ctx.ui.notify("Usage: /council <question or review task>", "info");
        return;
      }
      pi.sendUserMessage(`Use the council tool on this question, then synthesize its disagreements and evidence:\n\n${args}`);
    },
  });
}
