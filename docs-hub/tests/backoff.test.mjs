import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { parse as parseYaml } from "yaml";
import { advanceState, nextDelayMinutes } from "../server/backoff.mjs";
import { dueSources, refresh } from "../server/pipeline.mjs";

test("adaptive unchanged schedule backs off to two hours", () => {
  assert.deepEqual(
    [0, 1, 2, 3, 4, 5].map((attempt) => nextDelayMinutes("unchanged", attempt)),
    [10, 15, 30, 60, 120, 120]
  );
});

test("a detected change returns to five minutes", () => {
  const state = advanceState({ attempt: 4 }, "changed", 0);
  assert.equal(state.attempt, 0);
  assert.equal(Date.parse(state.nextCheckAt), 5 * 60_000);
});

test("errors use bounded retry backoff", () => {
  assert.deepEqual(
    [0, 1, 2, 3, 4, 8].map((attempt) => nextDelayMinutes("error", attempt)),
    [5, 10, 15, 30, 60, 60]
  );
});

test("an empty schedule checks configured sources and records a failed refresh", async (t) => {
  const stateDir = await mkdtemp(path.join(os.tmpdir(), "docs-hub-empty-schedule-"));
  t.after(() => rm(stateDir, { recursive: true, force: true }));
  const statePath = path.join(stateDir, "refresh-state.yml");
  await writeFile(statePath, "");

  assert.deepEqual(await dueSources(stateDir), ["example-docs"]);
  await assert.rejects(
    () =>
      refresh({
        stateDir,
        clients: {
          gitea: {
            async prepare() {
              throw new Error("mirror unavailable");
            }
          }
        }
      }),
    /example-docs: mirror unavailable/u
  );
  const state = parseYaml(await readFile(statePath, "utf8"));
  assert.equal(state["example-docs"].error, "mirror unavailable");
  assert.ok(Date.parse(state["example-docs"].nextCheckAt) > Date.now());
});
