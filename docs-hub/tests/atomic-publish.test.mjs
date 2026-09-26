import assert from "node:assert/strict";
import { access, mkdir, readlink, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  buildAndPublish,
  loadConfiguration,
  rendererBuildChanged,
  rendererFingerprint,
  scheduledRefreshSource
} from "../server/pipeline.mjs";

const clients = {
  gitea: {
    browseUrl(repository, sha) {
      return `https://gitea.example/${repository}/src/commit/${sha}`;
    }
  }
};

test("a renderer image change invalidates an otherwise-current static release", async () => {
  const stateDir = await import("node:fs/promises").then(({ mkdtemp }) =>
    mkdtemp(path.join(os.tmpdir(), "docs-hub-renderer-"))
  );
  const release = path.join(stateDir, "releases", "current");
  await mkdir(release, { recursive: true });
  await symlink(path.join("releases", "current"), path.join(stateDir, "current"));

  assert.equal(await rendererBuildChanged(stateDir), true);
  await writeFile(
    path.join(release, "build.json"),
    JSON.stringify({ rendererFingerprint: await rendererFingerprint() })
  );
  assert.equal(await rendererBuildChanged(stateDir), false);
  assert.equal(await scheduledRefreshSource(stateDir, []), null);
  assert.equal(await scheduledRefreshSource(stateDir, ["example-docs"]), "example-docs");

  await writeFile(path.join(release, "build.json"), JSON.stringify({ rendererFingerprint: "stale" }));
  assert.equal(await scheduledRefreshSource(stateDir, []), "");
});

test("a deliberately failed rebuild preserves the previous current release", async () => {
  const stateDir = await import("node:fs/promises").then(({ mkdtemp }) =>
    mkdtemp(path.join(os.tmpdir(), "docs-hub-atomic-"))
  );
  await mkdir(path.join(stateDir, "releases", "known-good"), { recursive: true });
  await writeFile(path.join(stateDir, "releases", "known-good", "index.html"), "known good");
  await symlink(path.join("releases", "known-good"), path.join(stateDir, "current"));
  const { sources, visuals } = await loadConfiguration();
  await assert.rejects(() => buildAndPublish({ sources, visuals, clients, stateDir }), /no synchronized source snapshot/u);
  assert.equal(await readlink(path.join(stateDir, "current")), path.join("releases", "known-good"));
});

test("a broken visual asset fails before the current release advances", async () => {
  const stateDir = await import("node:fs/promises").then(({ mkdtemp }) =>
    mkdtemp(path.join(os.tmpdir(), "docs-hub-broken-asset-"))
  );
  await mkdir(path.join(stateDir, "releases", "known-good"), { recursive: true });
  await writeFile(path.join(stateDir, "releases", "known-good", "index.html"), "known good");
  await symlink(path.join("releases", "known-good"), path.join(stateDir, "current"));
  const { sources, visuals } = await loadConfiguration();
  const sha = "b".repeat(40);
  for (const source of sources) {
    const snapshot = path.join(stateDir, "sources", source.id, sha, "docs");
    await mkdir(snapshot, { recursive: true });
    const content =
      source.id === "example-docs"
        ? ':::visual{format="excalidraw" src="missing.excalidraw" caption="Missing fixture"}'
        : `# ${source.label}`;
    await writeFile(path.join(snapshot, "index.md"), content);
    await symlink(sha, path.join(stateDir, "sources", source.id, "current"));
  }
  await assert.rejects(
    () => buildAndPublish({ sources, visuals, clients, stateDir }),
    /visual asset does not exist inside the source snapshot/u
  );
  assert.equal(await readlink(path.join(stateDir, "current")), path.join("releases", "known-good"));
});

test("a relative Markdown image is published before Astro builds the document", async () => {
  const stateDir = await import("node:fs/promises").then(({ mkdtemp }) =>
    mkdtemp(path.join(os.tmpdir(), "docs-hub-relative-image-"))
  );
  const { sources, visuals } = await loadConfiguration();
  const sha = "c".repeat(40);
  const snapshot = path.join(stateDir, "sources", "example-docs", sha, "docs", "architecture");
  await mkdir(snapshot, { recursive: true });
  await writeFile(path.join(snapshot, "target.md"), "# Target\n\n![Target architecture](target.svg)\n");
  await writeFile(
    path.join(snapshot, "target.svg"),
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><title>Target</title></svg>\n'
  );
  await symlink(sha, path.join(stateDir, "sources", "example-docs", "current"));

  await buildAndPublish({ sources, visuals, clients, stateDir });

  const release = await import("node:fs/promises").then(({ realpath }) => realpath(path.join(stateDir, "current")));
  await access(path.join(release, "repos", "example-docs", "docs", "architecture", "target", "index.html"));
  await access(path.join(release, "repos", "example-docs", "docs", "architecture", "target.svg"));
});
