# docker-images

Pre-built Docker images for self-hosted services. Published to `ghcr.io/alxleo/`.

## Custom Images

Auto-discovered from `*/Dockerfile`. Per-image config in optional `.ci.json` files.

| Image | Why | Remove when |
|-------|-----|-------------|
| `caddy-cloudflare` | Caddy + Cloudflare DNS + docker-proxy + tailscale plugins | Never (plugins aren't in upstream) |
| `cadvisor` | Built from source (Docker 29+ compat fix) | ghcr.io/google/cadvisor publishes v0.57+ |
| `mcp-git` | Git MCP server with ssh deps + Docker secret injection | Upstream publishes official Docker image |
| `mcp-auth-proxy` | OAuth proxy with VARCHAR(255) fix | Upstream merges the fix |
| `pr-reviewer` | AI PR reviewer with Claude/Gemini/Codex CLIs | Never (custom multi-model engine) |
| `semaphore` | Semaphore UI + homelab tools (sops, age, dig, jq, rsync) | Never (tooling layer always needed) |
| `dagu-ops` | Dagu + restic + rclone + Docker CLI | Never (ops tooling layer) |
| `restic-scheduler` | restic + rclone + supercronic | Never (supercronic layer) |
| `mcp-substack` | Custom MCP server for authenticated Substack content | Never (custom server) |
| `pihole-exporter` | Upstream exporter wrapped for Docker secret injection | Upstream supports file-based secret ingestion |

## MCP Service Images

17 containerized MCP servers driven by [`mcp-images.json`](mcp-images.json). All follow the same pattern:
- npm-based: `mcp/Dockerfile.npm` | Python-based: `mcp/Dockerfile.python`
- Shared `mcp/entrypoint.py` handles mcp-proxy startup, tool filtering, and secret injection
- Health: `GET /ping` on port `8080` (from `mcp-proxy`, validated by CI)

## Adding a New Image

1. Create a directory with a `Dockerfile`
2. Push

That's it. The CI auto-discovers images from `*/Dockerfile`. Optional `.ci.json` for non-defaults:

```json
{
  "platforms": "linux/amd64,linux/arm64",
  "test_commands": ["docker run --rm $IMAGE_REF sh -c 'tool --version'"]
}
```

Conventions (no `.ci.json` needed): platforms=amd64, tag=latest, push=docker, no tests.

## CI & Automation

| Workflow | Trigger | What |
|----------|---------|------|
| **Build** | Push to main, PRs | Auto-discover + matrix build, Trivy scan, test, push to GHCR |
| **Lint** | Push, PRs | ruff, shellcheck, hadolint, actionlint, yamllint, zizmor, lychee |
| **Release Please** | Push to main | Conventional commits -> version bumps + changelogs + GitHub Releases |
| **Mirror base images** | Weekly + PRs | Mirrors Docker Hub base images to GHCR, checks PRs for missing mirrors |
| **Cleanup GHCR** | Monthly | Deletes untagged manifests, keeps 5 most recent versions |

Base images mirrored to `ghcr.io/alxleo/base-images/` -- zero Docker Hub dependency for builds.

## Testing

| Suite | What | Trigger |
|-------|------|---------|
| Per-image tests | `.ci.json` `test_commands` (smoke tests, pytest) | Image changes |
| Caddy routing E2E | Snippet imports, handle_path, redirects | caddy-cloudflare changes |
| MCP E2E stack | Full Caddy -> mcp-proxy -> MCP server chain | MCP or caddy changes |
| MCP smoke | Standalone health + MCP initialize | MCP canaries (npm + Python) |
