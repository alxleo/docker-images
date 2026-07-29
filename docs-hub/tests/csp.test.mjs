import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
