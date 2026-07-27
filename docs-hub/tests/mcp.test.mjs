import assert from "node:assert/strict";
import test from "node:test";
import { contentType, mcpCall } from "../server/controller.mjs";

test("MCP initialize exposes a stateless tools capability", async () => {
  const response = await mcpCall({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} });
  assert.equal(response.result.protocolVersion, "2025-03-26");
  assert.deepEqual(response.result.capabilities, { tools: { listChanged: false } });
});

test("MCP lists the three read-only documentation tools only", async () => {
  const response = await mcpCall({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
  assert.deepEqual(
    response.result.tools.map(({ name }) => name),
    ["list_sources", "search_docs", "get_document"]
  );
  assert.ok(response.result.tools.every(({ name }) => !name.includes("refresh")));
});

test("browser runtime assets use executable and searchable MIME types", () => {
  assert.equal(contentType("worker.mjs"), "text/javascript; charset=utf-8");
  assert.equal(contentType("font.woff2"), "font/woff2");
  assert.equal(contentType("captions.vtt"), "text/vtt; charset=utf-8");
  assert.equal(contentType("place.geojson"), "application/geo+json; charset=utf-8");
});
