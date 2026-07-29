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
