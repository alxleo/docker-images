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
| name | directory name | `"name": "mcp-git"` |
| platforms | `linux/amd64` | `"platforms": "linux/amd64,linux/arm64"` |
| tag | `latest` | `"tag": "v2.11"` |
| push method | `docker` (auto: `buildx` if multi-platform) | derived |
| trivyignore | `{dir}/.trivyignore` if exists | derived |
| tests | none | `"test_commands": [...]` |

### Composite Action

`.github/actions/build-image/action.yml` handles the common build+scan flow:
QEMU setup -> buildx (GHCR-mirrored BuildKit) -> build (with GHA cache) -> Trivy scan.
Callers handle tests, GHCR login, and pushing the final image.

### Image Types

| Type | How | Examples |
|------|-----|---------|
| **Custom images** | `*/Dockerfile` + `.ci.json` | pr-reviewer, caddy-cloudflare, semaphore |
| **MCP images** | `mcp-images.json` -> `Dockerfile.npm` or `.python` | mcp-reddit, mcp-arxiv |
| **Patched upstream** | Clone at tag + minimal fix | mcp-auth-proxy (VARCHAR), cadvisor (Docker 29) |

### Versioning (release-please)

Conventional commits -> release-please -> version bump + CHANGELOG -> GitHub Release + git tag.

- Commit format: `type(scope): message` where scope = directory name
- `fix(pr-reviewer): ...` -> patch bump, `feat(caddy-cloudflare): ...` -> minor bump
- release-please opens a grouped PR with all pending version bumps
- Merging the release PR creates GitHub Releases + tags
- Build workflow tags images with the version from `.release-please-manifest.json`
- VERSION tags only pushed on release builds (`refs/tags/*`), not every push

Config: `release-please-config.json` (components), `.release-please-manifest.json` (current versions).

### GHCR Base Image Mirrors

All Dockerfiles pull from `ghcr.io/alxleo/base-images/` instead of Docker Hub. Zero rate limit issues.

- `scripts/mirror-base-images.sh` mirrors images (amd64+arm64) via `docker buildx imagetools create`
- Weekly refresh via `.github/workflows/mirror-base-images.yml`
- PRs that touch Dockerfiles trigger `--check` mode (fails if mirror is missing)
- To update after version bump: run the script or trigger the workflow manually

### OCI Labels

All Dockerfiles include `LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images`.
This auto-links GHCR packages to the repo so `GITHUB_TOKEN` can push.

## CI Workflows

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| Build | `build-images.yml` | push main, PRs, dispatch | Auto-discover, matrix build, test, push |
| Lint | `lint.yml` | push, PRs | ruff, pytest, shellcheck, hadolint, actionlint, yamllint, zizmor, lychee, log audit |
| Release Please | `release-please.yml` | push main | Conventional commit -> version bump + CHANGELOG |
| Mirror | `mirror-base-images.yml` | weekly, PRs (check), dispatch | GHCR base image mirrors |
| Cleanup | `cleanup-ghcr.yml` | monthly | Delete untagged GHCR manifests |

### Pre-commit hooks

gitleaks, shellcheck, hadolint, actionlint, yamllint, zizmor, ruff, log audit (no sensitive data at INFO), no-unicode-in-config, secret file blocking, caddy fmt.

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
# Build any image
docker build -t test caddy-cloudflare/

# Run discover script
bash scripts/discover-images.sh | jq .

# Mirror base images
bash scripts/mirror-base-images.sh --check  # verify mirrors exist
bash scripts/mirror-base-images.sh           # full mirror
```

Do NOT add `justfile`, `Makefile`, or wrapper scripts -- there are no manual commands to automate beyond `docker build`.
