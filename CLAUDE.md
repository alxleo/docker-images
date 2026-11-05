# THIS IS A PUBLIC REPOSITORY

Everything committed here is visible to the entire internet.

NEVER commit: secrets, API keys, tokens, passwords, internal IPs, private hostnames,
SOPS-encrypted files, .env files, or anything from private repositories.

## Architecture

### Auto-Discovery

Any directory with a `Dockerfile` is an image. No central manifest to maintain.

`scripts/discover-images.sh` scans `*/Dockerfile`, reads optional `.ci.json` per directory, outputs a GitHub Actions matrix. Convention over configuration:

| Field | Default | Override via `.ci.json` |
|-------|---------|----------------------|
| name | directory name | `"name": "published-image-name"` |
| platforms | `linux/amd64,linux/arm64` | `"platforms": "linux/arm64"` |
| tag | `latest` | `"tag": "v2.11"` |
| tests | none | `"test_commands": [...]` |
| dockle exemptions | none | `"dockle": {"ignore": {CODE: reason}, "accept_keys": {ENV_KEY: reason}}` |

### Build Flow

Custom images build through the reusable `.github/workflows/build-custom-image.yml`:
a native-architecture matrix builds and tests each platform, then publishes the
tested digests. BuildKit is `docker.io/moby/buildkit`, digest-pinned.
`.github/actions/build-image/action.yml` (QEMU -> buildx -> build with GHA cache)
is kept, but no workflow in this repository calls it.
Vulnerability scanning runs weekly in `maintenance.yml`, not inline.
Trivy exceptions live beside the image: `.trivyignore.yaml` scopes each CVE to
one file path inside the image (so a tool version bump expires it), plain
`.trivyignore` applies image-wide; an image may carry only one of the two.

### Image Types

| Type | How | Examples |
|------|-----|---------|
| **Custom images** | `*/Dockerfile` + `.ci.json` | caddy-cloudflare, docs-hub, mcp-reddit |
| **MCP images** | `mcp-images.json` -> purpose-fit Dockerfile | mcp-brave, mcp-arxiv |
| **Patched upstream** | Clone at tag + minimal fix | mcp-auth-proxy (Alpine runtime — /bin/sh required by homelab compose) |

### Base Image Strategy

| Base | Used by | Why |
|------|---------|-----|
| `node:26-alpine` | Dockerfile.npm, Dockerfile.python, Dockerfile.slack, docs-hub, transmute (frontend stage) | Smallest viable Node base, no setuid binaries |
| `node:26-slim` | Dockerfile.arxiv proxy stage | Supplies a glibc Node binary for the python-slim final image |
| `python:3.14-alpine` | mcp-reddit, homelab-observer | Pure Python deps, Alpine viable |
| `python:3.14-slim` | finrobot-mcp, openbb-mcp, Dockerfile.arxiv | glibc wheels (pymupdf in Dockerfile.arxiv) |
| `alpine:3.23` | mcp-auth-proxy (runtime), docs-hub | Already Alpine; mcp-auth-proxy needs /bin/sh for homelab compose entrypoint (see alxleo/homelab#401) |
| `golang:1.26-bookworm` | mcp-auth-proxy, Dockerfile.slack (build stages) | Build stages that rebuild upstream Go sources |
| `caddy:2.11` / `2.11-builder` | caddy-cloudflare | xcaddy plugin build |
| `ubuntu:24.04` | gitea-ci-runner (arc-runner inherits it) | CI runner base |

All images build multi-arch (amd64 + arm64) and have `HEALTHCHECK` where they
`EXPOSE`. All have a non-root `USER` except the five with a recorded
`conftest:exempt=user_required` reason: caddy-cloudflare, litellm,
mcp-auth-proxy, open-webui and transmute.

### Versioning

Each custom image gets a monotonically incrementing build counter tracked via
git tags. MCP images from `mcp-images.json` publish only `:{tag}` and `:latest`.

- Base version: the `tag` field in `.ci.json` (defaults to `latest`)
- Build counter: stored as `{name}/{tag}-build.{N}` git tags, auto-incremented on every push to main
- Pushed tags: `:latest`, `:{tag}` (from `.ci.json`), and `:{tag}-build.{N}` (build version)
- Conventional commits are used for commit messages and readability; no automated release tooling runs

### GHCR Base Image Mirrors

All Dockerfiles pull from `ghcr.io/alxleo/base-images/` instead of Docker Hub. Zero rate limit issues.

- `scripts/mirror-base-images.sh` mirrors images (amd64+arm64) via `docker buildx imagetools create`
- Weekly refresh via `.github/workflows/mirror-base-images.yml`
- To update after version bump: run the script or trigger the workflow manually

### OCI Labels

All Dockerfiles include `LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images`.
This auto-links GHCR packages to the repo so `GITHUB_TOKEN` can push.

## CI Workflows

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| Build | `build-images.yml` | push main, PRs, dispatch, mirror refresh | Auto-discover, matrix build, test, push; gitleaks scan on PRs; a successful mirror run rebuilds everything |
| Lint | `lint.yml` | push, PRs | coding-standards (MegaLinter), conftest, pytest |
| Maintenance | `maintenance.yml` | after the weekly mirror rebuild, dispatch | Trivy vuln scan, dockle CIS scan |
| Mirror | `mirror-base-images.yml` | weekly, dispatch | GHCR base image mirrors |
| NixOS runner | `build-nixos-runner-image.yml` | push main, PRs (path-filtered), dispatch | Build the NixOS runner image |
| ToolHive fleet | `toolhive-fleet.yml` | push main, PRs (path-filtered), dispatch | Live MCP contract checks for the ToolHive fleet |

### Dockerfile Policies

`policy/dockerfile.rego` enforces structural Dockerfile invariants via conftest:
- `USER` must exist in the final stage (non-root)
- `EXPOSE` implies `HEALTHCHECK` must exist
- `COPY`/`ADD` destinations and `WORKDIR` must not target `/root/` in the final stage
- Exemptions via `# conftest:exempt=rule_name` comments in the Dockerfile

`policy/compose.rego` enforces compose-file invariants:
- Volume mounts (bind, named, tmpfs) must not target `/root/` in containers
- `working_dir` must not target `/root/`
- Exemptions via `x-conftest-exempt: [rule_name]` extension field on the service

`hadolint` requires `org.opencontainers.image.source` label (DL3049 via `label-schema`).

### Pre-commit hooks

gitleaks, shellcheck, hadolint, check-user-has-group (USER numeric ID must have preceding addgroup), actionlint, yamllint, zizmor, ruff, no-unicode-in-config, secret file blocking, caddy fmt.

## Development

### Adding a new image

1. Create `my-image/Dockerfile`
2. Add `LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images`
3. Optional: `my-image/.ci.json` for tests, multi-platform, or custom tag
4. Push. CI auto-discovers and builds it.

### Patched upstream pattern

```dockerfile
RUN git clone --branch v2.5.3 --depth 1 https://github.com/upstream/repo.git .
RUN sed -i 's/broken/fixed/g' path/to/file.go   # link to upstream issue
```

Header comment: upstream repo, issue link, what's fixed, when to remove.

### MCP images

Edit `mcp-images.json` to add/update. Fields: `name`, `dockerfile`, `build_args`, `tag` (required); `description`, `secrets` (optional).

`mcp-defaults.json` has runtime defaults (`health_path`, `health_port`, `mcp_endpoint`). Downstream repos read these.

### Testing locally

```bash
# Fast discovery, manifest, unit, and policy preflight
just check

# Build one image and run its .ci.json tests against that exact local image
just test-image caddy-cloudflare

# Mirror base images (run after bumping a base image version)
bash scripts/mirror-base-images.sh
```

Keep `justfile` recipes thin. Image-specific behavior belongs in `.ci.json` so
local and GitHub Actions verification use the same test commands.
