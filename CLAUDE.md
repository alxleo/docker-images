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

### Composite Action

`.github/actions/build-image/action.yml` handles the common build flow:
QEMU setup -> buildx (GHCR-mirrored BuildKit) -> build (with GHA cache).
Callers handle tests, GHCR login, and pushing the final image.
Vulnerability scanning runs weekly in `maintenance.yml`, not inline.

### Image Types

| Type | How | Examples |
|------|-----|---------|
| **Custom images** | `*/Dockerfile` + `.ci.json` | caddy-cloudflare, docs-hub, mcp-reddit |
| **MCP images** | `mcp-images.json` -> purpose-fit Dockerfile | mcp-brave, mcp-arxiv |
| **Patched upstream** | Clone at tag + minimal fix | mcp-auth-proxy (Alpine runtime — /bin/sh required by homelab compose) |

### Base Image Strategy

| Base | Used by | Why |
|------|---------|-----|
| `node:26-alpine` | Dockerfile.npm, Dockerfile.python | Smallest viable Node base, no setuid binaries |
| `node:26-slim` | Dockerfile.arxiv proxy stage | Python C extensions (pymupdf) need glibc |
| `python:3.14-alpine` | mcp-reddit | Pure Python deps, Alpine viable |
| `alpine:3.23` | pihole-exporter, mcp-auth-proxy (runtime) | Already Alpine; mcp-auth-proxy needs /bin/sh for homelab compose entrypoint (see alxleo/homelab#401) |

All images build multi-arch (amd64 + arm64). All have `USER` (non-root) and `HEALTHCHECK` where applicable.

### Versioning

Each image gets a monotonically incrementing build counter tracked via git tags.

- Base version: the `tag` field in `.ci.json` (defaults to `latest`)
- Build counter: stored as `{name}/{tag}-build.{N}` git tags, auto-incremented on every push to main
- Pushed tags: `:latest`, `:{tag}` (from `.ci.json`), and `:{tag}-build.{N}` (build version)
- The `tags: ['*/v*']` trigger in `build-images.yml` is inert — actual build tags follow the `{name}/{tag}-build.{N}` pattern and do not match `*/v*`
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
| Build | `build-images.yml` | push main, PRs, tags, dispatch | Auto-discover, matrix build, test, push; gitleaks scan on PRs |
| Lint | `lint.yml` | push, PRs | coding-standards (MegaLinter), conftest, pytest |
| Maintenance | `maintenance.yml` | weekly, dispatch | Trivy vuln scan, dockle CIS scan, action updates |
| Mirror | `mirror-base-images.yml` | weekly, dispatch | GHCR base image mirrors |

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
