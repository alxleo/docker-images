import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { buildDocument, extractText } from "../server/corpus.mjs";
import { assertVisualSize, renderedDocumentUrl, resolveVisualAsset } from "../server/pipeline.mjs";
import { safeMarkdown, stripExecutableMarkdown } from "../server/sanitize.mjs";

const TEST_ROOT = path.dirname(fileURLToPath(import.meta.url));
const context = {
  formats: {
    excalidraw: { extensions: [".excalidraw"] },
    pdf: { extensions: [".pdf"] },
    video: { extensions: [".mp4"] }
  },
  assetUrl: (asset, format) => (format === "html" ? `https://assets.example/${asset}` : `/repo/${asset}`),
  editUrl: (asset) => `https://gitea.example/repo/${asset}`
};

test("imported MDX and HTML scripts cannot execute", () => {
  const input = [
    'import Danger from "./Danger.jsx";',
    "<script>window.pwned = true</script>",
    '<img src="ok.png" onerror="window.pwned=true">',
    "<Danger />",
    "[bad](javascript:alert(1))"
  ].join("\n");
  const result = stripExecutableMarkdown(input);
  assert.doesNotMatch(result, /\bimport\b/u);
  assert.doesNotMatch(result, /<script/iu);
  assert.doesNotMatch(result, /\sonerror=/iu);
  assert.doesNotMatch(result, /javascript:/iu);
  assert.doesNotMatch(result, /<Danger/u);
});

test("raw repository HTML and active URL schemes never enter rendered Markdown", () => {
  const result = stripExecutableMarkdown(
    [
      '<form action="https://example.invalid/collect"><input name="secret"></form>',
      '<svg><a href="data:text/html,unsafe">unsafe</a></svg>',
      "[unsafe](vbscript:alert(1))"
    ].join("\n")
  );
  assert.doesNotMatch(result, /<form|<input|<svg|<a/iu);
  assert.doesNotMatch(result, /(?:data|vbscript)\s*:/iu);
});

test("only allowlisted visual directives become owned placeholders", () => {
  const result = safeMarkdown(
    ':::visual{format="excalidraw" src="scene.excalidraw" caption="System map" fallback="scene.svg"}',
    context
  );
  assert.match(result, /class="docs-visual"/u);
  assert.match(result, /data-format="excalidraw"/u);
  assert.match(result, /data-caption="System map"/u);
  assert.match(result, /data-fallback="\/repo\/scene.svg"/u);
});

test("Excalidraw labels and notebook saved output enter the corpus", () => {
  const scene = Buffer.from(JSON.stringify({ elements: [{ text: "Mirror pipeline" }] }));
  assert.match(extractText("scene.excalidraw", scene), /Mirror pipeline/u);
  const notebook = Buffer.from(
    JSON.stringify({
      cells: [{ source: ["# Result"], outputs: [{ text: ["saved output"] }] }]
    })
  );
  assert.match(extractText("result.ipynb", notebook), /saved output/u);
});

test("media directives retain an inert transcript asset without weakening the caption requirement", () => {
  const result = safeMarkdown(
    ':::visual{format="video" src="demo.mp4" caption="Deployment walkthrough" transcript="demo.vtt"}',
    context
  );
  assert.match(result, /data-transcript="\/repo\/demo.vtt"/u);
  assert.match(result, /data-caption="Deployment walkthrough"/u);
});

test("visual directives with an empty accessible caption fail the candidate build", () => {
  assert.throws(
    () => safeMarkdown(':::visual{format="pdf" src="runbook.pdf" caption="   "}', context),
    /caption must not be empty/u
  );
});

test("unknown visual formats fail instead of invoking imported components", () => {
  assert.throws(
    () => safeMarkdown(':::visual{format="arbitrary-jsx" src="x.js" caption="Unsafe"}', context),
    /not allowlisted/u
  );
});

test("visual assets cannot escape their source namespace and must exist", () => {
  const input = {
    documentPath: "docs/runbook.md",
    routeName: "example-docs",
    existingFiles: new Set(["docs/scene.excalidraw"]),
    formats: context.formats,
    format: "excalidraw",
    assetOrigin: "https://assets.example"
  };
  assert.equal(
    resolveVisualAsset({ ...input, asset: "scene.excalidraw" }),
    "/repos/example-docs/docs/scene.excalidraw"
  );
  assert.throws(
    () => resolveVisualAsset({ ...input, asset: "../../secret.excalidraw" }),
    /relative same-snapshot/u
  );
  assert.throws(() => resolveVisualAsset({ ...input, asset: "/etc/passwd" }), /relative same-snapshot/u);
  assert.throws(() => resolveVisualAsset({ ...input, asset: "missing.excalidraw" }), /does not exist/u);
});

test("standalone HTML is published only on the sandboxed asset origin", () => {
  const input = {
    documentPath: "docs/runbook.md",
    routeName: "example-docs",
    existingFiles: new Set(["docs/untrusted.html"]),
    formats: { html: { extensions: [".html"] } },
    format: "html",
    assetOrigin: "https://assets.example"
  };
  assert.equal(
    resolveVisualAsset({ ...input, asset: "untrusted.html" }),
    "https://assets.example/sandbox/example-docs/docs/untrusted.html"
  );
});

test("corpus links match Starlight routes while raw assets remain byte-addressable", () => {
  assert.equal(renderedDocumentUrl("/repos/example-docs", "docs/guide.md"), "/repos/example-docs/docs/guide/");
  assert.equal(renderedDocumentUrl("/repos/example-docs", "docs/index.mdx"), "/repos/example-docs/docs/");
  assert.equal(
    renderedDocumentUrl("/repos/example-docs", "docs/diagram.svg"),
    "/repos/example-docs/docs/diagram.svg"
  );
});

test("registered visual size limits fail closed", () => {
  const formats = {
    pdf: { extensions: [".pdf"], max_bytes: 10 },
    plotly: { extensions: [".plotly.json"], max_bytes: 20 }
  };
  assert.doesNotThrow(() => assertVisualSize("guide.pdf", 10, formats));
  assert.throws(() => assertVisualSize("guide.pdf", 11, formats), /limit is 10/u);
  assert.throws(() => assertVisualSize("chart.plotly.json", 21, formats), /plotly asset/u);
});

test("PDF text is extracted into the normalized corpus at build time", async () => {
  const buffer = await readFile(path.join(TEST_ROOT, "../fixtures/public/visuals/sample.pdf"));
  const document = await buildDocument({
    source: "example-docs",
    relativePath: "docs/sample.pdf",
    sha: "a".repeat(40),
    mimeType: "application/pdf",
    renderedUrl: "/repos/example-docs/docs/sample.pdf",
    buffer,
    builtAt: "2026-07-27T00:00:00.000Z"
  });
  assert.match(document.text, /Docs Hub PDF fixture/u);
});
