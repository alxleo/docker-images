import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { inlineScriptHashes } from "../server/controller.mjs";

test("CSP hashes permit only the exact inline Astro bootstrap scripts", () => {
  const first = "window.Astro = {};";
  const second = "\ncustomElements.define('astro-island', class extends HTMLElement {});\n";
  const html = [
    "<html><head>",
    `<script>${first}</script>`,
    '<script type="module" src="/_astro/page.js"></script>',
    `<script>${second}</script>`,
    "</head></html>"
  ].join("");
  const expected = [first, second].map(
    (script) => `'sha256-${createHash("sha256").update(script).digest("base64")}'`
  );

  assert.deepEqual(inlineScriptHashes(html), expected);
  assert.deepEqual(inlineScriptHashes(Buffer.from(html)), expected);
});

test("CSP hashes deduplicate identical inline scripts", () => {
  const html = "<script>same()</script><script nonce=\"ignored\">same()</script>";

  assert.equal(inlineScriptHashes(html).length, 1);
});

test("Vega-Lite uses the CSP-safe expression interpreter path", async () => {
  const source = await readFile(
    new URL("../src/components/VisualRuntime.tsx", import.meta.url),
    "utf8"
  );

  assert.match(source, /await embed\(surface, spec, \{[\s\S]*ast: true,[\s\S]*renderer: "svg"/u);
  assert.doesNotMatch(source, /unsafe-eval/u);
});

test("Vega-Lite fixture evaluates without the JavaScript Function constructor", async () => {
  const spec = JSON.parse(
    await readFile(new URL("../fixtures/public/visuals/chart.vl.json", import.meta.url), "utf8")
  );
  const originalFunction = globalThis.Function;
  globalThis.Function = function blockedFunction() {
    throw new Error("Vega attempted runtime JavaScript compilation");
  };
  try {
    const [{ compile }, vega, { expressionInterpreter }] = await Promise.all([
      import("vega-lite"),
      import("vega"),
      import("vega-interpreter")
    ]);
    const runtime = vega.parse(compile(spec).spec, {}, { ast: true });
    const view = new vega.View(runtime, { expr: expressionInterpreter, renderer: "none" });
    await view.runAsync();
    assert.equal(view.data("source_0").length, 2);
  } finally {
    globalThis.Function = originalFunction;
  }
});
