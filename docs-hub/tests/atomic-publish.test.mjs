import assert from "node:assert/strict";
import { mkdir, readlink, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  buildAndPublish,
  loadConfiguration,
  rendererBuildChanged,
  rendererFingerprint
} from "../server/pipeline.mjs";

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
});

test("a deliberately failed rebuild preserves the previous current release", async () => {
  const stateDir = await import("node:fs/promises").then(({ mkdtemp }) =>
    mkdtemp(path.join(os.tmpdir(), "docs-hub-atomic-"))
  );
  await mkdir(path.join(stateDir, "releases", "known-good"), { recursive: true });
  await writeFile(path.join(stateDir, "releases", "known-good", "index.html"), "known good");
  await symlink(path.join("releases", "known-good"), path.join(stateDir, "current"));
  const { sources, visuals } = await loadConfiguration();
  await assert.rejects(() => buildAndPublish({ sources, visuals, stateDir }), /no synchronized source snapshot/u);
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
    () => buildAndPublish({ sources, visuals, stateDir }),
    /visual asset does not exist inside the source snapshot/u
  );
  assert.equal(await readlink(path.join(stateDir, "current")), path.join("releases", "known-good"));
});
