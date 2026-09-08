import assert from "node:assert/strict";
import { mkdtemp, readFile, readlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";
import tar from "tar-stream";
import { clientForSource, GitHubClient, syncSource } from "../server/pipeline.mjs";

async function gzippedArchive(files) {
  const pack = tar.pack();
  const chunks = [];
  const finished = new Promise((resolve, reject) => {
    pack.on("data", (chunk) => chunks.push(chunk));
    pack.on("end", resolve);
    pack.on("error", reject);
  });
  for (const [name, content] of Object.entries(files)) {
    pack.entry({ name }, content);
  }
  pack.finalize();
  await finished;
  return gzipSync(Buffer.concat(chunks));
}

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

test("a GitHub branch response publishes the exact archived SHA", async () => {
  const sha = "c".repeat(40);
  const archive = await gzippedArchive({ "homelab-fixture/docs/index.md": "# GitHub canonical" });
  const calls = [];
  const client = new GitHubClient({
    token: "test-token",
    fetcher: async (url, options) => {
      const address = String(url);
      calls.push([address, options]);
      if (address === "https://api.github.com/repos/alxleo/homelab/branches/main") {
        return Response.json({ commit: { sha } });
      }
      if (address === `https://api.github.com/repos/alxleo/homelab/tarball/${sha}`) {
        return new Response(null, {
          status: 302,
          headers: { location: `https://codeload.github.com/alxleo/homelab/tar.gz/${sha}` }
        });
      }
      if (address === `https://codeload.github.com/alxleo/homelab/tar.gz/${sha}`) {
        return new Response(archive, { status: 200 });
      }
      throw new Error(`unexpected request: ${address}`);
    }
  });
  const stateDir = await mkdtemp(path.join(os.tmpdir(), "docs-hub-github-publish-"));
  const source = { id: "homelab", provider: "github", repository: "alxleo/homelab", branch: "main" };

  assert.deepEqual(await syncSource({ source, client, stateDir }), { changed: true, sha });
  assert.equal(await readlink(path.join(stateDir, "sources", "homelab", "current")), sha);
  assert.equal(
    await readFile(path.join(stateDir, "sources", "homelab", sha, "docs", "index.md"), "utf8"),
    "# GitHub canonical"
  );
  assert.deepEqual(
    calls.map(([address]) => address),
    [
      "https://api.github.com/repos/alxleo/homelab/branches/main",
      `https://api.github.com/repos/alxleo/homelab/tarball/${sha}`,
      `https://codeload.github.com/alxleo/homelab/tar.gz/${sha}`
    ]
  );
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
