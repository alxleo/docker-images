import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { syncSource } from "../server/pipeline.mjs";

test("every due source check synchronizes its Gitea pull mirror before reading the branch", async () => {
  const calls = [];
  const client = {
    async mirrorSync(repository) {
      calls.push(["mirror-sync", repository]);
    },
    async branch(repository, branch) {
      calls.push(["branch", repository, branch]);
      return { commit: { id: "a".repeat(40) } };
    },
    async archive() {
      throw new Error("archive should not be reached for this ordering assertion");
    }
  };
  const stateDir = await mkdtemp(path.join(os.tmpdir(), "docs-hub-mirror-"));
  await assert.rejects(
    () =>
      syncSource({
        source: { id: "example-docs", repository: "example/docs", branch: "main" },
        client,
        stateDir
      }),
    /archive should not be reached/u
  );
  assert.deepEqual(calls.slice(0, 2), [
    ["mirror-sync", "example/docs"],
    ["branch", "example/docs", "main"]
  ]);
});
