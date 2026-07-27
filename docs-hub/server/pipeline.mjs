import { createGunzip } from "node:zlib";
import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import {
  access,
  cp,
  mkdir,
  readFile,
  readdir,
  readlink,
  rename,
  rm,
  stat,
  symlink,
  writeFile
} from "node:fs/promises";
import path from "node:path";
import { pipeline as streamPipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";
import { minimatch } from "minimatch";
import tar from "tar-stream";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { advanceState } from "./backoff.mjs";
import { buildDocument } from "./corpus.mjs";
import { safeMarkdown } from "./sanitize.mjs";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CONFIG_ROOT = path.resolve(process.env.DOCS_HUB_CONFIG_ROOT ?? "/config");
const FIXTURE_ROOT = path.join(APP_ROOT, "fixtures");
const GITEA_URL = (process.env.DOCS_HUB_GITEA_URL ?? "http://localhost:3000").replace(/\/+$/u, "");
const ASSET_ORIGIN = (process.env.DOCS_HUB_ASSET_ORIGIN ?? "http://localhost:8081").replace(/\/+$/u, "");
const MAX_ARCHIVE_FILE_BYTES = 512 * 1024 * 1024;
const RETAIN_RELEASES = 3;
const RETAIN_SOURCE_SNAPSHOTS = 2;

function titleFromPath(relativePath) {
  const base = path.basename(relativePath, path.extname(relativePath));
  return base
    .replace(/[-_]+/gu, " ")
    .replace(/\b\w/gu, (character) => character.toUpperCase());
}

function mimeType(relativePath) {
  const extension = path.extname(relativePath).toLowerCase();
  return (
    {
      ".md": "text/markdown",
      ".mdx": "text/markdown",
      ".svg": "image/svg+xml",
      ".png": "image/png",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".webp": "image/webp",
      ".pdf": "application/pdf",
      ".json": "application/json",
      ".geojson": "application/geo+json",
      ".yaml": "application/yaml",
      ".yml": "application/yaml",
      ".ipynb": "application/x-ipynb+json",
      ".html": "text/html",
      ".mp3": "audio/mpeg",
      ".m4a": "audio/mp4",
      ".wav": "audio/wav",
      ".mp4": "video/mp4",
      ".webm": "video/webm",
      ".gltf": "model/gltf+json",
      ".glb": "model/gltf-binary",
      ".stl": "model/stl"
    }[extension] ?? "application/octet-stream"
  );
}

async function exists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function walk(root, prefix = "") {
  const output = [];
  for (const entry of await readdir(path.join(root, prefix), { withFileTypes: true })) {
    const relative = path.posix.join(prefix, entry.name);
    if (entry.isDirectory()) output.push(...(await walk(root, relative)));
    else if (entry.isFile()) output.push(relative);
  }
  return output;
}

function mergedSources(config) {
  const defaults = config.defaults ?? {};
  return (config.sources ?? []).map((source) => ({
    owner: defaults.owner,
    branch: defaults.branch ?? "main",
    include: defaults.include ?? ["**/*.md"],
    exclude: defaults.exclude ?? [],
    visual_policy: defaults.visual_policy ?? "standard",
    ...source
  }));
}

export async function loadConfiguration() {
  const sources = parseYaml(await readFile(path.join(CONFIG_ROOT, "sources.yml"), "utf8"));
  const visuals = parseYaml(await readFile(path.join(CONFIG_ROOT, "visual-registry.yml"), "utf8"));
  return { sources: mergedSources(sources), visuals };
}

export class GiteaClient {
  constructor({ baseUrl, token }) {
    this.baseUrl = baseUrl.replace(/\/+$/u, "");
    this.token = token;
  }

  async request(route, options = {}) {
    const response = await fetch(`${this.baseUrl}/api/v1${route}`, {
      ...options,
      headers: {
        Accept: "application/json",
        Authorization: `token ${this.token}`,
        ...(options.headers ?? {})
      },
      redirect: "error"
    });
    if (!response.ok) {
      throw new Error(`Gitea ${options.method ?? "GET"} ${route} returned ${response.status}`);
    }
    return response;
  }

  async mirrorSync(repository) {
    await this.request(`/repos/${repository}/mirror-sync`, { method: "POST" });
  }

  async branch(repository, branch) {
    return this.request(`/repos/${repository}/branches/${encodeURIComponent(branch)}`).then((response) =>
      response.json()
    );
  }

  async archive(repository, sha) {
    return this.request(`/repos/${repository}/archive/${encodeURIComponent(sha)}.tar.gz`);
  }
}

async function extractArchive(response, destination) {
  const extractor = tar.extract();
  const pending = [];
  extractor.on("entry", (header, stream, next) => {
    const parts = header.name.split("/").slice(1);
    const relative = path.posix.normalize(parts.join("/"));
    if (!relative || relative.startsWith("../") || path.posix.isAbsolute(relative)) {
      stream.resume();
      stream.on("end", next);
      return;
    }
    const target = path.join(destination, relative);
    if (header.type === "directory") {
      pending.push(mkdir(target, { recursive: true }));
      stream.resume();
      stream.on("end", next);
      return;
    }
    if (header.type !== "file") {
      stream.resume();
      stream.on("end", next);
      return;
    }
    if (Number(header.size) > MAX_ARCHIVE_FILE_BYTES) {
      stream.resume();
      extractor.destroy(new Error(`${relative}: archive member exceeds the extraction safety limit`));
      return;
    }
    const task = mkdir(path.dirname(target), { recursive: true })
      .then(() => streamPipeline(stream, createWriteStream(target, { mode: 0o640 })))
      .then(next)
      .catch((error) => extractor.destroy(error));
    pending.push(task);
  });
  const body = response.body;
  if (!body) throw new Error("Gitea archive response had no body");
  await streamPipeline(body, createGunzip(), extractor);
  await Promise.all(pending);
}

async function atomicallyPoint(linkPath, relativeTarget) {
  const nextLink = `${linkPath}.next`;
  await rm(nextLink, { force: true });
  await symlink(relativeTarget, nextLink);
  await rename(nextLink, linkPath);
}

async function pruneDirectories(root, keep, limit) {
  const entries = await readdir(root, { withFileTypes: true }).catch(() => []);
  const candidates = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith(".staging-"))
      .map(async (entry) => ({
        name: entry.name,
        modified: (await stat(path.join(root, entry.name))).mtimeMs
      }))
  );
  candidates.sort((left, right) => right.modified - left.modified);
  const retained = new Set(keep);
  for (const candidate of candidates) {
    if (retained.size >= limit) break;
    retained.add(candidate.name);
  }
  await Promise.all(
    candidates
      .filter((candidate) => !retained.has(candidate.name))
      .map((candidate) => rm(path.join(root, candidate.name), { recursive: true, force: true }))
  );
}

export async function syncSource({ source, client, stateDir }) {
  // A Gitea pull mirror is only useful as the source of truth when each due
  // check asks Gitea to fetch its upstream before reading the branch SHA.
  // Browser reloads never enter this pipeline; only scheduled or explicitly
  // authenticated refreshes do.
  await client.mirrorSync(source.repository);
  const branch = await client.branch(source.repository, source.branch);
  const sha = branch?.commit?.id;
  if (!/^[0-9a-f]{40,64}$/u.test(sha ?? "")) {
    throw new Error(`${source.id}: Gitea returned an invalid branch SHA`);
  }
  const sourceRoot = path.join(stateDir, "sources", source.id);
  await mkdir(sourceRoot, { recursive: true });
  const currentLink = path.join(sourceRoot, "current");
  let currentSha = "";
  try {
    currentSha = path.basename(await readlink(currentLink));
  } catch {
    // First sync has no current source.
  }
  if (sha === currentSha) return { changed: false, sha };

  const finalSnapshot = path.join(sourceRoot, sha);
  if (!(await exists(finalSnapshot))) {
    const staging = path.join(sourceRoot, `.staging-${sha}-${crypto.randomUUID()}`);
    await mkdir(staging, { recursive: true });
    try {
      await extractArchive(await client.archive(source.repository, sha), staging);
      await rename(staging, finalSnapshot);
    } catch (error) {
      await rm(staging, { recursive: true, force: true });
      throw error;
    }
  }
  await atomicallyPoint(currentLink, sha);
  return { changed: true, sha };
}

function included(source, relativePath) {
  const inRoot = source.roots.some(
    (root) => relativePath === root || relativePath.startsWith(`${root.replace(/\/+$/u, "")}/`)
  );
  return (
    inRoot &&
    source.include.some((pattern) => minimatch(relativePath, pattern, { dot: true })) &&
    !source.exclude.some((pattern) => minimatch(relativePath, pattern, { dot: true, nocase: true }))
  );
}

export function assertVisualSize(relativePath, byteLength, formats) {
  const matches = Object.entries(formats)
    .flatMap(([format, spec]) => (spec.extensions ?? []).map((extension) => ({ format, extension, spec })))
    .filter(({ extension }) => relativePath.toLowerCase().endsWith(String(extension).toLowerCase()))
    .sort((left, right) => String(right.extension).length - String(left.extension).length);
  if (matches.length === 0) return;
  const { format, spec } = matches[0];
  const maximum = Number(spec.max_bytes);
  if (!Number.isSafeInteger(maximum) || maximum <= 0) {
    throw new Error(`${format}: visual registry max_bytes must be a positive integer`);
  }
  if (byteLength > maximum) {
    throw new Error(`${relativePath}: ${format} asset is ${byteLength} bytes; limit is ${maximum}`);
  }
}

export function resolveVisualAsset({
  asset,
  documentPath,
  routeName,
  existingFiles,
  formats,
  format,
  assetOrigin
}) {
  if (
    !asset ||
    asset.includes("\\") ||
    asset.split("/").includes("..") ||
    path.posix.isAbsolute(asset) ||
    /^[a-z][a-z0-9+.-]*:/iu.test(asset)
  ) {
    throw new Error(`${documentPath}: visual asset must be a relative same-snapshot path`);
  }
  const relative = path.posix.normalize(path.posix.join(path.posix.dirname(documentPath), asset));
  if (relative === ".." || relative.startsWith("../") || !existingFiles.has(relative)) {
    throw new Error(`${documentPath}: visual asset does not exist inside the source snapshot: ${asset}`);
  }
  if (format === "svg" && !relative.toLowerCase().endsWith(".svg")) {
    throw new Error(`${documentPath}: fallback must be an SVG asset`);
  }
  if (format === "transcript" && !relative.toLowerCase().endsWith(".vtt")) {
    throw new Error(`${documentPath}: transcript must be a WebVTT asset`);
  }
  const spec = formats[format];
  if (spec) {
    const lower = relative.toLowerCase();
    if (!(spec.extensions ?? []).some((extension) => lower.endsWith(String(extension).toLowerCase()))) {
      throw new Error(`${documentPath}: ${asset} does not match the ${format} registry extensions`);
    }
  }
  const published =
    ["d2", "graphviz", "plantuml"].includes(format) ? `/repos/${routeName}/${relative}.svg` : `/repos/${routeName}/${relative}`;
  return format === "html" ? `${assetOrigin}/sandbox/${routeName}/${relative}` : published;
}

async function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: { ...process.env, ...(options.env ?? {}) },
      stdio: options.input ? ["pipe", "pipe", "pipe"] : ["ignore", "pipe", "pipe"]
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve(Buffer.concat(stdout));
      } else {
        reject(new Error(`${command} exited ${code}: ${Buffer.concat(stderr).toString("utf8").slice(-2000)}`));
      }
    });
    if (options.input) child.stdin.end(options.input);
  });
}

async function renderBuildDiagram(sourcePath, destinationPath) {
  const extension = path.extname(sourcePath).toLowerCase();
  await mkdir(path.dirname(destinationPath), { recursive: true });
  if (extension === ".d2") {
    await run("d2", ["--layout=elk", "--theme=0", sourcePath, destinationPath]);
  } else if (extension === ".dot" || extension === ".gv") {
    await run("dot", ["-Tsvg", sourcePath, "-o", destinationPath]);
  } else if (extension === ".puml" || extension === ".plantuml") {
    const input = await readFile(sourcePath);
    const output = await run("java", ["-Djava.awt.headless=true", "-jar", "/opt/plantuml.jar", "-tsvg", "-pipe"], {
      input
    });
    await writeFile(destinationPath, output);
  }
}

export function renderedDocumentUrl(assetBase, relativePath) {
  if (!/\.mdx?$/iu.test(relativePath)) return `${assetBase}/${relativePath}`;
  const withoutExtension = relativePath.replace(/\.mdx?$/iu, "");
  if (path.posix.basename(withoutExtension).toLowerCase() === "index") {
    const directory = path.posix.dirname(withoutExtension);
    return directory === "." ? `${assetBase}/` : `${assetBase}/${directory}/`;
  }
  return `${assetBase}/${withoutExtension}/`;
}

function frontmatter(title, description) {
  return `---\ntitle: ${JSON.stringify(title)}\ndescription: ${JSON.stringify(description)}\n---\n\n`;
}

async function materializeSource({ source, snapshot, contentRoot, publicRoot, corpus, builtAt, visualFormats }) {
  const sha = path.basename(await readlink(snapshot));
  const sourceRoot = path.resolve(path.dirname(snapshot), sha);
  const allFiles = await walk(sourceRoot);
  const files = allFiles.filter((relativePath) => included(source, relativePath));
  const existingFiles = new Set(files);
  const editBase = `${GITEA_URL}/${source.repository}/src/commit/${sha}`;
  const routeName = source.id;
  if (!/^[A-Za-z0-9._-]+$/u.test(routeName)) {
    throw new Error(`${source.id}: repository name is unsafe for a published route`);
  }
  const assetBase = `/repos/${routeName}`;
  const index = [
    frontmatter(source.label, `${source.repository} at ${sha.slice(0, 12)}`),
    `This repository is published without merging or rewriting its source tree.\n\n`,
    `Commit: \`${sha}\` · [Browse source](${editBase})\n`
  ].join("");
  await mkdir(path.join(contentRoot, "repos", routeName), { recursive: true });
  await writeFile(path.join(contentRoot, "repos", routeName, "index.md"), index);

  for (const relativePath of files) {
    const input = path.join(sourceRoot, relativePath);
    const buffer = await readFile(input);
    assertVisualSize(relativePath, buffer.length, visualFormats);
    const lower = relativePath.toLowerCase();
    const renderedUrl = lower.endsWith(".html")
      ? `${ASSET_ORIGIN}/sandbox/${routeName}/${relativePath}`
      : renderedDocumentUrl(assetBase, relativePath);
    corpus.push(
      await buildDocument({
        source: source.id,
        relativePath,
        sha,
        mimeType: mimeType(relativePath),
        renderedUrl,
        buffer,
        builtAt
      })
    );
    if (lower.endsWith(".md") || lower.endsWith(".mdx")) {
      const outputRelative = relativePath.replace(/\.mdx?$/iu, ".md");
      const output = path.join(contentRoot, "repos", routeName, outputRelative);
      await mkdir(path.dirname(output), { recursive: true });
      const context = {
        formats: visualFormats,
        assetUrl: (asset, format) => {
          return resolveVisualAsset({
            asset,
            documentPath: relativePath,
            routeName,
            existingFiles,
            formats: visualFormats,
            format,
            assetOrigin: ASSET_ORIGIN
          });
        },
        editUrl: (asset) => {
          const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(relativePath), asset));
          return `${editBase}/${resolved}`;
        }
      };
      const sanitized = safeMarkdown(buffer.toString("utf8"), context);
      await writeFile(
        output,
        `${frontmatter(titleFromPath(relativePath), `${source.repository}/${relativePath} at ${sha.slice(0, 12)}`)}${sanitized}`
      );
    } else {
      const namespace = lower.endsWith(".html") ? "sandbox" : "repos";
      const output = path.join(publicRoot, namespace, routeName, relativePath);
      await mkdir(path.dirname(output), { recursive: true });
      await writeFile(output, buffer);
      if ([".d2", ".dot", ".gv", ".puml", ".plantuml"].includes(path.extname(lower))) {
        await renderBuildDiagram(input, `${output}.svg`);
      }
    }
  }
  return {
    id: source.id,
    repository: source.repository,
    branch: source.branch,
    commitSha: sha,
    route: `/repos/${routeName}/`
  };
}

export async function buildAndPublish({ sources, visuals, stateDir }) {
  const builtAt = new Date().toISOString();
  const buildId = `${builtAt.replace(/[-:.]/gu, "").slice(0, 15)}-${crypto.randomUUID().slice(0, 8)}`;
  const workRoot = path.join(stateDir, "work", buildId);
  const contentRoot = path.join(workRoot, "content");
  const publicRoot = path.join(workRoot, "public");
  const releaseRoot = path.join(stateDir, "releases", buildId);
  const corpus = [];
  const sourceBuilds = [];
  await mkdir(contentRoot, { recursive: true });
  await mkdir(publicRoot, { recursive: true });
  await cp(path.join(FIXTURE_ROOT, "content"), contentRoot, { recursive: true });
  await cp(path.join(FIXTURE_ROOT, "public"), publicRoot, { recursive: true });
  const acceptancePath = path.join(contentRoot, "visual-acceptance", "index.md");
  const acceptance = await readFile(acceptancePath, "utf8");
  await writeFile(acceptancePath, acceptance.replaceAll("__DOCS_ASSET_ORIGIN__", ASSET_ORIGIN));
  await writeFile(path.join(publicRoot, "visual-registry.json"), `${JSON.stringify(visuals, null, 2)}\n`);

  try {
    for (const source of sources) {
      const snapshot = path.join(stateDir, "sources", source.id, "current");
      if (!(await exists(snapshot))) throw new Error(`${source.id}: no synchronized source snapshot`);
      sourceBuilds.push(
        await materializeSource({
          source,
          snapshot,
          contentRoot,
          publicRoot,
          corpus,
          builtAt,
          visualFormats: visuals.formats ?? {}
        })
      );
    }
    await mkdir(path.join(stateDir, ".astro"), { recursive: true });
    await mkdir(path.join(stateDir, ".astro-cache"), { recursive: true });
    const nodeModulesLink = path.join(stateDir, "node_modules");
    try {
      await symlink(path.join(APP_ROOT, "node_modules"), nodeModulesLink);
    } catch (error) {
      if (error?.code !== "EEXIST" || (await readlink(nodeModulesLink)) !== path.join(APP_ROOT, "node_modules")) {
        throw error;
      }
    }
    await run(path.join(APP_ROOT, "node_modules", ".bin", "astro"), ["build", "--outDir", releaseRoot], {
      cwd: APP_ROOT,
      env: {
        DOCS_HUB_CONTENT_ROOT: contentRoot,
        DOCS_HUB_PUBLIC_ROOT: publicRoot
      }
    });
    await writeFile(path.join(releaseRoot, "corpus.json"), `${JSON.stringify(corpus)}\n`);
    await writeFile(
      path.join(releaseRoot, "build.json"),
      `${JSON.stringify({ buildId, builtAt, sources: sourceBuilds }, null, 2)}\n`
    );
    await rm(workRoot, { recursive: true, force: true });
    await atomicallyPoint(path.join(stateDir, "current"), path.join("releases", buildId));
    const cleanupErrors = [];
    try {
      await pruneDirectories(path.join(stateDir, "releases"), new Set([buildId]), RETAIN_RELEASES);
      for (const source of sources) {
        const sourceRoot = path.join(stateDir, "sources", source.id);
        const currentSha = path.basename(await readlink(path.join(sourceRoot, "current")));
        await pruneDirectories(sourceRoot, new Set([currentSha]), RETAIN_SOURCE_SNAPSHOTS);
      }
    } catch (error) {
      // Publication is already atomic and complete. Cleanup failure must not
      // remove the now-current release or misreport a successful publication.
      cleanupErrors.push(error instanceof Error ? error.message : String(error));
    }
    return { buildId, builtAt, documents: corpus.length, cleanupErrors };
  } catch (error) {
    await rm(workRoot, { recursive: true, force: true });
    await rm(releaseRoot, { recursive: true, force: true });
    throw error;
  }
}

export async function refresh({ sourceId = "", client, stateDir }) {
  const { sources, visuals } = await loadConfiguration();
  const selected = sourceId ? sources.filter((source) => source.id === sourceId) : sources;
  if (selected.length === 0) throw new Error(`unknown source: ${sourceId}`);
  const statePath = path.join(stateDir, "refresh-state.yml");
  const state = (await exists(statePath)) ? parseYaml(await readFile(statePath, "utf8")) : {};
  let changed = false;
  const results = [];
  for (const source of selected) {
    try {
      const result = await syncSource({ source, client, stateDir });
      changed ||= result.changed;
      state[source.id] = {
        ...(state[source.id] ?? {}),
        sha: result.sha,
        ...advanceState(state[source.id], result.changed ? "changed" : "unchanged")
      };
      results.push({ source: source.id, ...result });
    } catch (error) {
      state[source.id] = {
        ...(state[source.id] ?? {}),
        ...advanceState(state[source.id], "error"),
        error: error instanceof Error ? error.message : String(error)
      };
      results.push({ source: source.id, error: state[source.id].error });
    }
  }
  await mkdir(stateDir, { recursive: true });
  const nextState = `${statePath}.next`;
  await writeFile(nextState, stringifyYaml(state));
  await rename(nextState, statePath);
  const failed = results.filter((result) => result.error);
  if (failed.length > 0) throw new Error(failed.map((result) => `${result.source}: ${result.error}`).join("; "));
  const currentExists = await exists(path.join(stateDir, "current"));
  const build = changed || !currentExists ? await buildAndPublish({ sources, visuals, stateDir }) : null;
  return { changed, build, results };
}

export async function dueSources(stateDir, now = Date.now()) {
  const { sources } = await loadConfiguration();
  const statePath = path.join(stateDir, "refresh-state.yml");
  if (!(await exists(statePath))) return sources.map((source) => source.id);
  const state = parseYaml(await readFile(statePath, "utf8"));
  return sources
    .filter((source) => !state[source.id]?.nextCheckAt || Date.parse(state[source.id].nextCheckAt) <= now)
    .map((source) => source.id);
}
