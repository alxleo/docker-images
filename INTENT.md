# INTENT: Pre-homelab image verification

## Problem Statement

This repository publishes mutable `:latest` images consumed directly by homelab,
but its local verification path does not faithfully reproduce the per-image CI
contract. Custom-image tests can fall back to a duplicated, stale tag manifest
instead of the image that was just built, and the public `images.json` inventory
consumed by homelab is not checked against the images this repository actually
builds.

## Success Criteria

- [ ] One local command validates image discovery, manifest parity, unit tests,
      and Dockerfile/Compose policies.
- [ ] One local command builds a named custom image for the Docker host's native
      architecture and runs that image's existing `.ci.json` test commands.
- [ ] CI functional tests target the image built in the current job.
- [ ] `images.json` contains exactly the auto-discovered custom images and
      `mcp-images.json` images, with no duplicates.
- [ ] Custom Python MCP servers use the current MCP SDK major and pass an
      initialize plus tools/list handshake through `mcp-proxy`.
- [ ] Homelab's compose-image validator accepts the local `images.json`.

## User Flows

### Primary Flow: Fast repository preflight

1. A maintainer changes image or shared infrastructure code.
2. The maintainer runs `just check`.
3. Discovery, inventory, unit, and policy failures are reported locally.

### Primary Flow: Targeted image verification

1. A maintainer runs `just test-image <name-or-context>`.
2. The repository resolves the image's `.ci.json`, builds a local image, and
   exports that exact image reference to its existing test commands.
3. The command fails before publication if the build or contract tests fail.

### Error Flow: Unknown image

1. The maintainer supplies an unknown image name or context.
2. The command prints the available names and exits non-zero without building.

## Anti-Success

- A green test run that exercised an older image from GHCR.
- A second hand-maintained custom-image manifest that can drift.
- Coupling this public repository to private homelab files or credentials.
- Turning the fast preflight into an all-images, multi-architecture build.

## Out of Scope

- Broad dependency and upstream-version sweeps beyond blockers exposed by this
  preflight.
- Removing retired or currently unconsumed images.
- Repairing scheduled maintenance and base-image mirror workflows.
- Replacing the existing GitHub Actions build pipeline.

## Open Questions (resolved)

- Q: Should local targeted builds reproduce multi-architecture publication?
  A: No. They use the Docker host's native architecture, matching CI's loaded
     test image while keeping feedback fast.
- Q: Should CI bootstrap commands such as `sudo apt-get` run locally?
  A: No. Local prerequisites are explicit; `.ci.json` `test_setup` remains
     CI-only.

## Fit with Wider Picture

This is the first bounded slice of repository maintenance. It establishes a
trustworthy, fast oracle before version updates, wrapper retirement, and service
removal are attempted in later reviewable slices.

---
*Intent captured: 2026-07-29*
*Ready for planning: Yes*
