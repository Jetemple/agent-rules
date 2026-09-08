import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const MAX_FILES = 5_000;
const MAX_DIRECTORY_ENTRIES = 20_000;
const MAX_FILE_BYTES = 1024 * 1024;
const MAX_READ_OUTPUT_BYTES = 50 * 1024;
const MAX_MATCHES = 100;
const MAX_RENDERED_LINE = 500;
const SKIP_DIRECTORIES = new Set([".git", ".hg", ".svn", "node_modules", ".venv", "venv", "coverage"]);
const SENSITIVE_PATH =
  /(^|\/)(?:\.env(?:\.|$)|\.envrc$|\.git(?:\/|$)|\.git-credentials$|\.ssh(?:\/|$)|\.aws(?:\/|$)|\.kube(?:\/|$)|\.docker(?:\/|$)|\.azure(?:\/|$)|\.terraform(?:\/|$)|\.config\/(?:gcloud|gh|hub)(?:\/|$)|auth\.json$|\.netrc$|\.npmrc$|\.pypirc$|\.pgpass$|\.my\.cnf$|\.vault-token$|\.litellm_envs$|\.llm_env$|terraform\.tfstate(?:\.|$)|application_default_credentials\.json$|service[-_]?account[^/]*\.json$|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.|$)|[^/]+\.(?:key|pem|p12|pfx)$|credentials?(?:\.[^/]*)?(?=\/|$)|secrets?(?:\.[^/]*)?(?=\/|$)|[^/]*(?:client[-_]?secret|[-_]credentials?)(?:\.(?:json|ya?ml|toml|ini|conf|config))?(?=\/|$)|(?:[^/]*[._-])?(?:token|api[-_]?key|password|private[-_]?key)(?:[._-][^/]*)?(?=\/|$))/i;

function canonicalExisting(filePath: string): string {
  try {
    return fs.realpathSync(filePath);
  } catch {
    return path.resolve(filePath);
  }
}

function isInside(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function slash(filePath: string): string {
  return filePath.replaceAll(path.sep, "/");
}

function sameFile(left: fs.Stats, right: fs.Stats): boolean {
  return left.dev === right.dev && left.ino === right.ino;
}

function resolveSafePath(cwd: string, rawPath: string): string {
  const normalized = rawPath.startsWith("@") ? rawPath.slice(1) : rawPath;
  const root = canonicalExisting(cwd);
  const candidate = canonicalExisting(path.resolve(cwd, normalized));

  if (!isInside(root, candidate)) {
    throw new Error("Child agents cannot access paths outside their working directory.");
  }
  if (SENSITIVE_PATH.test(slash(candidate))) {
    throw new Error("Child agents cannot access credential or secret paths.");
  }
  return candidate;
}

async function readSafeFile(cwd: string, rawPath: string): Promise<string> {
  const beforePath = resolveSafePath(cwd, rawPath);
  const beforeStat = await fs.promises.stat(beforePath);
  if (!beforeStat.isFile()) throw new Error(`Not a regular file: ${rawPath}`);
  if (beforeStat.size > MAX_FILE_BYTES) throw new Error(`File exceeds ${MAX_FILE_BYTES} bytes: ${rawPath}`);

  const handle = await fs.promises.open(beforePath, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const openedStat = await handle.stat();
    if (openedStat.nlink !== 1) throw new Error(`Hard-linked file blocked: ${rawPath}`);
    const afterPath = resolveSafePath(cwd, rawPath);
    const afterStat = await fs.promises.stat(afterPath);
    if (!sameFile(beforeStat, openedStat) || !sameFile(openedStat, afterStat)) {
      throw new Error(`File changed while being validated: ${rawPath}`);
    }

    const content = await handle.readFile("utf8");
    const finalPath = resolveSafePath(cwd, rawPath);
    const finalPathStat = await fs.promises.stat(finalPath);
    const finalHandleStat = await handle.stat();
    if (!sameFile(openedStat, finalHandleStat) || !sameFile(finalHandleStat, finalPathStat)) {
      throw new Error(`File changed while being read: ${rawPath}`);
    }
    return content;
  } finally {
    await handle.close();
  }
}

async function listSafeFiles(cwd: string, rawPath: string, signal?: AbortSignal): Promise<string[]> {
  const start = resolveSafePath(cwd, rawPath);
  const startStat = await fs.promises.stat(start);
  if (startStat.isFile()) return startStat.nlink === 1 && startStat.size <= MAX_FILE_BYTES ? [start] : [];
  if (!startStat.isDirectory()) return [];

  const files: string[] = [];
  const directories = [start];
  let entriesSeen = 0;

  while (directories.length > 0 && files.length < MAX_FILES && entriesSeen < MAX_DIRECTORY_ENTRIES) {
    if (signal?.aborted) throw new Error("File enumeration aborted");
    const queued = directories.pop()!;
    let directory: string;
    try {
      directory = resolveSafePath(cwd, queued);
    } catch {
      continue;
    }

    let opened: fs.Dir;
    try {
      opened = await fs.promises.opendir(directory);
    } catch {
      continue;
    }

    try {
      for await (const entry of opened) {
        entriesSeen++;
        if (entriesSeen > MAX_DIRECTORY_ENTRIES || files.length >= MAX_FILES) break;
        if (SKIP_DIRECTORIES.has(entry.name)) continue;
        if (entry.name.startsWith(".") && entry.name !== ".github") continue;

        const unresolved = path.join(directory, entry.name);
        let unresolvedStat: fs.Stats;
        try {
          unresolvedStat = await fs.promises.lstat(unresolved);
        } catch {
          continue;
        }
        if (unresolvedStat.isSymbolicLink()) continue;

        let candidate: string;
        try {
          candidate = resolveSafePath(cwd, unresolved);
        } catch {
          continue;
        }

        if (unresolvedStat.isDirectory()) {
          directories.push(candidate);
        } else if (unresolvedStat.isFile() && unresolvedStat.nlink === 1 && unresolvedStat.size <= MAX_FILE_BYTES) {
          files.push(candidate);
        }
      }
    } finally {
      await opened.close().catch(() => undefined);
    }
  }

  return files;
}

function truncateReadOutput(text: string): string {
  if (Buffer.byteLength(text, "utf8") <= MAX_READ_OUTPUT_BYTES) return text;
  const notice = "\n\n[Read output capped.]";
  const contentLimit = MAX_READ_OUTPUT_BYTES - Buffer.byteLength(notice, "utf8");
  let truncated = Buffer.from(text, "utf8").subarray(0, contentLimit).toString("utf8");
  truncated = truncated.replace(/\uFFFD+$/, "");
  return truncated + notice;
}

const SafeReadParams = Type.Object({
  path: Type.String({ maxLength: 4_096, description: "Non-sensitive file inside the child working directory" }),
  offset: Type.Optional(Type.Integer({ minimum: 1, description: "First line; default: 1" })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 2_000, description: "Maximum lines; default: 2,000" })),
});

const SafeGrepParams = Type.Object({
  query: Type.String({ maxLength: 512, description: "Literal text to search for" }),
  path: Type.Optional(
    Type.String({ maxLength: 4_096, description: "Directory or file inside the child working directory; default: ." }),
  ),
  ignoreCase: Type.Optional(Type.Boolean({ description: "Case-insensitive matching; default: false" })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: MAX_MATCHES, description: "Maximum matches" })),
});

const SafeFindParams = Type.Object({
  pattern: Type.String({ maxLength: 512, description: "File glob such as **/*.ts or exact filename" }),
  path: Type.Optional(
    Type.String({ maxLength: 4_096, description: "Directory inside the child working directory; default: ." }),
  ),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: MAX_MATCHES, description: "Maximum results" })),
});

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "safe_read",
    label: "Safe Read",
    description: "Read a bounded, non-sensitive file inside the child working directory.",
    promptSnippet: "Read repository files while enforcing workspace and credential boundaries",
    parameters: SafeReadParams,
    async execute(_id, params, signal, _onUpdate, ctx) {
      if (signal?.aborted) throw new Error("Safe read aborted");
      const content = await readSafeFile(ctx.cwd, params.path);
      if (content.includes("\0")) throw new Error(`Binary file blocked: ${params.path}`);
      const lines = content.split("\n");
      const offset = params.offset ?? 1;
      const limit = params.limit ?? 2_000;
      const selected = lines.slice(offset - 1, offset - 1 + limit).join("\n");
      return {
        content: [{ type: "text", text: truncateReadOutput(selected) }],
        details: { totalLines: lines.length, offset, linesReturned: Math.min(limit, Math.max(0, lines.length - offset + 1)) },
      };
    },
  });

  pi.registerTool({
    name: "safe_grep",
    label: "Safe Grep",
    description: "Search literal text only in bounded, non-sensitive files inside the child working directory.",
    promptSnippet: "Search repository file contents while filtering credential paths",
    parameters: SafeGrepParams,
    async execute(_id, params, signal, _onUpdate, ctx) {
      const files = await listSafeFiles(ctx.cwd, params.path ?? ".", signal);
      const needle = params.ignoreCase ? params.query.toLocaleLowerCase() : params.query;
      const limit = params.limit ?? MAX_MATCHES;
      const matches: string[] = [];

      for (const file of files) {
        if (signal?.aborted) throw new Error("Safe grep aborted");

        let content: string;
        try {
          content = await readSafeFile(ctx.cwd, file);
        } catch {
          continue;
        }
        if (content.includes("\0")) continue;

        const lines = content.split("\n");
        for (let index = 0; index < lines.length; index++) {
          const candidate = params.ignoreCase ? lines[index]!.toLocaleLowerCase() : lines[index]!;
          if (!candidate.includes(needle)) continue;
          const relative = slash(path.relative(ctx.cwd, file));
          const rendered = lines[index]!.slice(0, MAX_RENDERED_LINE);
          matches.push(`${relative}:${index + 1}:${rendered}`);
          if (matches.length >= limit) break;
        }
        if (matches.length >= limit) break;
      }

      return {
        content: [{ type: "text", text: matches.length > 0 ? matches.join("\n") : "No matches found." }],
        details: { filesScanned: files.length, matchLimitReached: matches.length >= limit ? limit : undefined },
      };
    },
  });

  pi.registerTool({
    name: "safe_find",
    label: "Safe Find",
    description: "Find non-sensitive files by glob inside the child working directory.",
    promptSnippet: "Find repository files while filtering credential paths",
    parameters: SafeFindParams,
    async execute(_id, params, signal, _onUpdate, ctx) {
      const files = await listSafeFiles(ctx.cwd, params.path ?? ".", signal);
      const limit = params.limit ?? MAX_MATCHES;
      const matches: string[] = [];

      for (const file of files) {
        const relative = slash(path.relative(ctx.cwd, file));
        let matched = false;
        try {
          matched = path.matchesGlob(relative, params.pattern) || path.matchesGlob(path.basename(file), params.pattern);
        } catch {
          throw new Error(`Invalid file glob: ${params.pattern}`);
        }
        if (!matched) continue;
        matches.push(relative);
        if (matches.length >= limit) break;
      }

      return {
        content: [{ type: "text", text: matches.length > 0 ? matches.join("\n") : "No files found." }],
        details: { filesScanned: files.length, resultLimitReached: matches.length >= limit ? limit : undefined },
      };
    },
  });
}
