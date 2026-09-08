import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { clientForSource, GitHubClient, syncSource } from "../server/pipeline.mjs";

test("every due source check synchronizes its Gitea pull mirror before reading the branch", async () => {
  const calls = [];
  const client = {
    async prepare(repository) {
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

test("a GitHub source never selects or synchronizes the Gitea mirror client", async () => {
  const calls = [];
  const gitea = new Proxy(
    {},
    {
      get() {
        throw new Error("GitHub source must not use Gitea");
      }
    }
  );
  const github = {
    async prepare(repository) {
      calls.push(["github-prepare", repository]);
    },
    async branch(repository, branch) {
      calls.push(["branch", repository, branch]);
      return { commit: { id: "b".repeat(40) } };
    },
    async archive() {
      throw new Error("archive should not be reached for this ordering assertion");
    }
  };
  const source = { id: "homelab", provider: "github", repository: "alxleo/homelab", branch: "main" };
  const client = clientForSource({ gitea, github }, source);
  assert.equal(client, github);
  const stateDir = await mkdtemp(path.join(os.tmpdir(), "docs-hub-github-"));
  await assert.rejects(() => syncSource({ source, client, stateDir }), /archive should not be reached/u);
  assert.deepEqual(calls.slice(0, 2), [
    ["github-prepare", "alxleo/homelab"],
    ["branch", "alxleo/homelab", "main"]
  ]);
});

test("GitHub archive redirects are fetched from codeload without forwarding credentials", async () => {
  const calls = [];
  const client = new GitHubClient({
    token: "test-token",
    fetcher: async (url, options) => {
      calls.push([String(url), options]);
      if (calls.length === 1) {
        return new Response(null, {
          status: 302,
          headers: { location: "https://codeload.github.com/alxleo/homelab/tar.gz/abc" }
        });
      }
      return new Response("archive", { status: 200 });
    }
  });
  const archive = await client.archive("alxleo/homelab", "abc");
  assert.equal(await archive.text(), "archive");
  assert.equal(calls.length, 2);
  assert.equal(calls[0][1].headers.Authorization, "Bearer test-token");
  assert.equal(calls[1][0], "https://codeload.github.com/alxleo/homelab/tar.gz/abc");
  assert.equal(Object.hasOwn(calls[1][1].headers, "Authorization"), false);
});
