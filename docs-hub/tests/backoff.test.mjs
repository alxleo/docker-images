import assert from "node:assert/strict";
import test from "node:test";
import { advanceState, nextDelayMinutes } from "../server/backoff.mjs";

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
