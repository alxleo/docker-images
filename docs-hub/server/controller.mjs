import { createHash, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { searchCorpus } from "./corpus.mjs";
import { dueSources, GiteaClient, loadConfiguration, refresh } from "./pipeline.mjs";

const MODE = process.env.DOCS_HUB_MODE ?? "controller";
const PORT = Number(process.env.DOCS_HUB_PORT ?? 8080);
const STATE_DIR = process.env.DOCS_HUB_STATE_DIR ?? "/state";
const GITEA_URL = process.env.DOCS_HUB_GITEA_URL ?? "http://localhost:3000";
const SITE_ORIGIN = process.env.DOCS_HUB_SITE_URL ?? "http://localhost:8080";
const ASSET_ORIGIN = process.env.DOCS_HUB_ASSET_ORIGIN ?? "http://localhost:8081";
const API_TOKEN_FILE = process.env.DOCS_HUB_API_TOKEN_FILE ?? "/run/secrets/docs_hub_api_token";
const GITEA_TOKEN_FILE = process.env.DOCS_HUB_GITEA_TOKEN_FILE ?? "/run/secrets/docs_hub_gitea_token";
const MAX_BODY_BYTES = 64 * 1024;
const TICK_MILLISECONDS = 60_000;
const STATIC_CACHE_SECONDS = 300;

let activeRefresh = null;
let lastRefresh = null;
let apiToken = "";
let giteaClient = null;

function log(level, event, detail = {}) {
  process.stdout.write(`${JSON.stringify({ timestamp: new Date().toISOString(), level, event, ...detail })}\n`);
}

async function readSecret(file) {
  return (await readFile(file, "utf8")).trim();
}

function secureEqual(left, right) {
  const leftHash = createHash("sha256").update(left).digest();
  const rightHash = createHash("sha256").update(right).digest();
  return timingSafeEqual(leftHash, rightHash);
}

function machineAuthorized(request) {
  const header = request.headers.authorization ?? "";
  return apiToken.length >= 32 && header.startsWith("Bearer ") && secureEqual(header.slice(7), apiToken);
}

function humanAuthorized(request) {
  const user = request.headers["remote-user"];
  const origin = request.headers.origin;
  return typeof user === "string" && user.length > 0 && (!origin || origin === SITE_ORIGIN);
}

function sendJson(response, status, value) {
  const body = `${JSON.stringify(value)}\n`;
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff"
  });
  response.end(body);
}

async function bodyJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new Error("request body too large");
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function currentRoot() {
  return realpath(path.join(STATE_DIR, "current"));
}

async function corpus() {
  return JSON.parse(await readFile(path.join(await currentRoot(), "corpus.json"), "utf8"));
}

async function sourceSummary() {
  const root = await currentRoot();
  const [{ sources }, build] = await Promise.all([
    loadConfiguration(),
    readFile(path.join(root, "build.json"), "utf8").then((value) => JSON.parse(value))
  ]);
  const published = new Map((build.sources ?? []).map((source) => [source.id, source]));
  return sources.map((source) => ({
    id: source.id,
    repository: source.repository,
    branch: source.branch,
    label: source.label,
    roots: source.roots,
    commitSha: published.get(source.id)?.commitSha ?? null,
    renderedUrl: published.get(source.id)?.route ?? null,
    buildTimestamp: build.builtAt ?? null
  }));
}

async function apiResponse(url) {
  if (url.pathname === "/api/v1/sources") return sourceSummary();
  if (url.pathname === "/api/v1/search") {
    return searchCorpus(await corpus(), {
      query: url.searchParams.get("q") ?? "",
      source: url.searchParams.get("source") ?? "",
      pathPrefix: url.searchParams.get("path") ?? ""
    });
  }
  const prefix = "/api/v1/document/";
  if (url.pathname.startsWith(prefix)) {
    const remainder = decodeURIComponent(url.pathname.slice(prefix.length));
    const separator = remainder.indexOf("/");
    if (separator < 1) return null;
    const source = remainder.slice(0, separator);
    const documentPath = remainder.slice(separator + 1);
    return (await corpus()).find((document) => document.source === source && document.path === documentPath) ?? null;
  }
  return undefined;
}

export async function mcpCall(body) {
  const id = body.id ?? null;
  if (body.method === "initialize") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: "2025-03-26",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "docs-hub", version: "0.1.0" }
      }
    };
  }
  if (body.method === "notifications/initialized") return null;
  if (body.method === "tools/list") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        tools: [
          {
            name: "list_sources",
            description: "List documentation sources and exact mirrored commit provenance.",
            inputSchema: { type: "object", additionalProperties: false }
          },
          {
            name: "search_docs",
            description: "Search normalized documentation and extracted visual text.",
            inputSchema: {
              type: "object",
              properties: {
                query: { type: "string" },
                source: { type: "string" },
                path: { type: "string" }
              },
              required: ["query"],
              additionalProperties: false
            }
          },
          {
            name: "get_document",
            description: "Retrieve one normalized document with repository, path, SHA, MIME type, and rendered URL.",
            inputSchema: {
              type: "object",
              properties: {
                source: { type: "string" },
                path: { type: "string" }
              },
              required: ["source", "path"],
              additionalProperties: false
            }
          }
        ]
      }
    };
  }
  if (body.method === "tools/call") {
    const name = body.params?.name;
    const input = body.params?.arguments ?? {};
    let value;
    if (name === "list_sources") value = await sourceSummary();
    else if (name === "search_docs") {
      value = searchCorpus(await corpus(), {
        query: input.query ?? "",
        source: input.source ?? "",
        pathPrefix: input.path ?? ""
      });
    } else if (name === "get_document") {
      value = (await corpus()).find(
        (document) => document.source === input.source && document.path === input.path
      );
    } else {
      return {
        jsonrpc: "2.0",
        id,
        error: { code: -32601, message: `unknown tool: ${name}` }
      };
    }
    return {
      jsonrpc: "2.0",
      id,
      result: {
        content: [{ type: "text", text: JSON.stringify(value ?? null) }],
        isError: value === undefined
      }
    };
  }
  return { jsonrpc: "2.0", id, error: { code: -32601, message: `unknown method: ${body.method}` } };
}

async function startRefresh(sourceId = "") {
  if (!giteaClient) throw new Error("refresh is unavailable in this process");
  if (activeRefresh) return activeRefresh;
  activeRefresh = refresh({ sourceId, client: giteaClient, stateDir: STATE_DIR })
    .then((result) => {
      lastRefresh = { status: "ok", at: new Date().toISOString(), result };
      log("info", "refresh.complete", { sourceId: sourceId || "all", changed: result.changed });
      return result;
    })
    .catch((error) => {
      lastRefresh = {
        status: "error",
        at: new Date().toISOString(),
        error: error instanceof Error ? error.message : String(error)
      };
      log("error", "refresh.failed", { sourceId: sourceId || "all", error: lastRefresh.error });
      throw error;
    })
    .finally(() => {
      activeRefresh = null;
    });
  return activeRefresh;
}

async function schedulerTick() {
  if (MODE !== "controller" || activeRefresh) return;
  const due = await dueSources(STATE_DIR);
  if (due.length === 0) return;
  // First run synchronizes all sources so a failed or missing source cannot
  // silently disappear from the aggregate. Later runs update one due source at
  // a time, retaining each source's independent adaptive schedule.
  const currentMissing = await currentRoot().then(
    () => false,
    () => true
  );
  await startRefresh(currentMissing ? "" : due[0]);
}

export function contentType(file) {
  const extension = path.extname(file).toLowerCase();
  return (
    {
      ".html": "text/html; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".mjs": "text/javascript; charset=utf-8",
      ".json": "application/json; charset=utf-8",
      ".geojson": "application/geo+json; charset=utf-8",
      ".svg": "image/svg+xml",
      ".png": "image/png",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".gif": "image/gif",
      ".webp": "image/webp",
      ".pdf": "application/pdf",
      ".mp3": "audio/mpeg",
      ".m4a": "audio/mp4",
      ".wav": "audio/wav",
      ".ogg": "audio/ogg",
      ".mp4": "video/mp4",
      ".webm": "video/webm",
      ".mov": "video/quicktime",
      ".vtt": "text/vtt; charset=utf-8",
      ".woff2": "font/woff2",
      ".gltf": "model/gltf+json",
      ".glb": "model/gltf-binary",
      ".stl": "model/stl"
    }[extension] ?? "application/octet-stream"
  );
}

export function inlineScriptHashes(payload) {
  const html = Buffer.isBuffer(payload) ? payload.toString("utf8") : String(payload);
  const hashes = [];
  const inlineScript = /<script\b(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)<\/script>/giu;
  for (const match of html.matchAll(inlineScript)) {
    hashes.push(`'sha256-${createHash("sha256").update(match[1]).digest("base64")}'`);
  }
  return [...new Set(hashes)];
}

async function serveStatic(request, response, requestPath) {
  const root = await currentRoot();
  const decoded = decodeURIComponent(requestPath);
  const clean = path.posix.normalize(decoded).replace(/^\/+/u, "");
  if (clean.startsWith("../")) return false;
  if (MODE !== "assets" && clean.startsWith("sandbox/")) return false;
  let target = path.join(root, clean);
  try {
    const targetStat = await stat(target);
    if (targetStat.isDirectory()) target = path.join(target, "index.html");
  } catch {
    target = path.join(root, clean, "index.html");
  }
  const resolved = await realpath(target).catch(() => "");
  if (!resolved.startsWith(`${root}${path.sep}`)) return false;
  const payload = await readFile(resolved).catch(() => null);
  if (!payload) return false;
  const headers = {
    "Content-Type": contentType(resolved),
    "Content-Length": payload.length,
    "Cache-Control": `public, max-age=${STATIC_CACHE_SECONDS}`,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer"
  };
  if (MODE === "assets" || path.extname(resolved).toLowerCase() === ".svg") {
    headers["Content-Security-Policy"] =
      "sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; media-src 'self'; font-src 'self'";
  } else {
    const scriptHashes =
      path.extname(resolved).toLowerCase() === ".html" ? inlineScriptHashes(payload) : [];
    headers["Content-Security-Policy"] =
      `default-src 'self'; script-src 'self' 'wasm-unsafe-eval' ${scriptHashes.join(" ")}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; frame-src ${ASSET_ORIGIN}; media-src 'self'`;
  }
  response.writeHead(200, headers);
  response.end(payload);
  return true;
}

async function handler(request, response) {
  const url = new URL(request.url ?? "/", SITE_ORIGIN);
  if (url.pathname === "/healthz") {
    const published = await currentRoot().then(
      () => true,
      () => false
    );
    return sendJson(response, published ? 200 : 503, {
      status: published ? "ok" : "not-published",
      mode: MODE,
      refreshRunning: Boolean(activeRefresh),
      lastRefresh
    });
  }

  if (MODE === "assets") {
    if (request.method !== "GET" && request.method !== "HEAD") return sendJson(response, 405, { error: "method" });
    if (!(await serveStatic(request, response, url.pathname))) sendJson(response, 404, { error: "not-found" });
    return;
  }

  const isApi = url.pathname.startsWith("/api/v1/");
  const isMcp = url.pathname === "/mcp";
  if (MODE === "machine" && (isApi || isMcp) && !machineAuthorized(request)) {
    return sendJson(response, 401, { error: "bearer token required" });
  }

  if (url.pathname === "/api/v1/admin/refresh") {
    if (MODE !== "controller" || request.method !== "POST" || !humanAuthorized(request)) {
      return sendJson(response, 403, { error: "authenticated human refresh only" });
    }
    const input = await bodyJson(request);
    const result = await startRefresh(typeof input.source === "string" ? input.source : "");
    return sendJson(response, 202, result);
  }

  if (isApi && request.method === "GET") {
    const value = await apiResponse(url);
    if (value === undefined || value === null) return sendJson(response, 404, { error: "not-found" });
    return sendJson(response, 200, value);
  }

  if (isMcp && request.method === "POST") {
    const result = await mcpCall(await bodyJson(request));
    if (result === null) {
      response.writeHead(202);
      response.end();
      return;
    }
    return sendJson(response, 200, result);
  }

  if (MODE === "machine") return sendJson(response, 404, { error: "not-found" });
  if (request.method !== "GET" && request.method !== "HEAD") return sendJson(response, 405, { error: "method" });
  if (!(await serveStatic(request, response, url.pathname))) sendJson(response, 404, { error: "not-found" });
}

export async function main() {
  if (MODE === "machine") apiToken = await readSecret(API_TOKEN_FILE);
  if (MODE === "controller") {
    giteaClient = new GiteaClient({ baseUrl: GITEA_URL, token: await readSecret(GITEA_TOKEN_FILE) });
    setInterval(() => void schedulerTick().catch((error) => log("error", "scheduler.failed", { error: String(error) })), TICK_MILLISECONDS);
    void schedulerTick().catch((error) => log("error", "initial-refresh.failed", { error: String(error) }));
  }
  const server = createServer((request, response) => {
    void handler(request, response).catch((error) => {
      log("error", "request.failed", { path: request.url, error: String(error) });
      if (!response.headersSent) sendJson(response, 500, { error: "internal" });
      else response.destroy();
    });
  });
  server.listen(PORT, "0.0.0.0", () => log("info", "server.ready", { port: PORT, mode: MODE }));
}

if (path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) await main();
