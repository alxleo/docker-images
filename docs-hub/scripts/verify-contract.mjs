import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const configRoot = path.resolve(process.env.DOCS_HUB_CONFIG_ROOT ?? "/config");
const sources = parseYaml(await readFile(path.join(configRoot, "sources.yml"), "utf8"));
const visuals = parseYaml(await readFile(path.join(configRoot, "visual-registry.yml"), "utf8"));
const dockerfile = await readFile(path.join(root, "Dockerfile"), "utf8");
const controller = await readFile(path.join(root, "server", "controller.mjs"), "utf8");
const pipeline = await readFile(path.join(root, "server", "pipeline.mjs"), "utf8");

const expectedFormats = [
  "excalidraw",
  "mermaid",
  "d2",
  "graphviz",
  "plantuml",
  "drawio",
  "vega-lite",
  "plotly",
  "pdf",
  "openapi",
  "svg",
  "raster",
  "gltf",
  "stl",
  "geojson",
  "notebook",
  "audio",
  "video",
  "html"
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(sources.version === 1, "sources manifest version must be 1");
assert(Array.isArray(sources.sources) && sources.sources.length > 0, "sources manifest must not be empty");
assert(!sources.defaults?.include?.includes("README.md"), "README ingestion must remain an explicit manifest edit");
assert(
  sources.defaults?.exclude?.some((pattern) => pattern.includes("secret")),
  "source ingestion must fail closed around secret-shaped paths"
);
for (const source of sources.sources) {
  assert(/^[A-Za-z0-9._-]+$/u.test(source.id ?? ""), "source id must be route-safe");
  assert(/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/u.test(source.repository ?? ""), "repository must be owner/name");
  assert(Array.isArray(source.roots) && source.roots.length > 0, `${source.id}: roots must not be empty`);
}
assert(visuals.version === 1, "visual registry version must be 1");
for (const format of expectedFormats) {
  const entry = visuals.formats[format];
  assert(entry, `visual format missing: ${format}`);
  for (const key of ["extensions", "rendering", "viewer", "max_bytes", "csp", "fallback", "verifier"]) {
    assert(Object.hasOwn(entry, key), `${format} missing ${key}`);
  }
}
assert(
  dockerfile.includes("ghcr.io/alxleo/base-images/"),
  "all Dockerfile base images must use the repository GHCR mirror"
);
assert(dockerfile.includes("npm ci --ignore-scripts"), "dependencies must install at image build time");
assert(!dockerfile.includes("npm install "), "runtime npm install is forbidden");
assert(dockerfile.includes("sha256sum -c -"), "downloaded renderers must be checksum verified");
assert(dockerfile.includes("HEALTHCHECK"), "an exposed image must declare a healthcheck");
assert(dockerfile.includes("USER 1000:1000"), "the final image user must be non-root");
assert(controller.includes('MODE !== "controller"'), "refresh must be controller-only");
assert(controller.includes("machineAuthorized"), "machine API must enforce a separate bearer token");
assert(pipeline.includes('process.env.DOCS_HUB_CONFIG_ROOT ?? "/config"'), "runtime config must be mounted");

process.stdout.write(
  `OK: Docs Hub generic contract (${sources.sources.length} fixture source, ${expectedFormats.length} visual formats)\n`
);
