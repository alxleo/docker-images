# docker-images

Pre-built Docker images for self-hosted services. Published to `ghcr.io/alxleo/`.

## Custom Images

Auto-discovered from `*/Dockerfile`. Per-image config in optional `.ci.json` files.

| Image | Why | Remove when |
|-------|-----|-------------|
| `caddy-cloudflare` | Caddy + Cloudflare DNS + docker-proxy + tailscale plugins | Never (plugins aren't in upstream) |
| `cadvisor` | Built from source (Docker 29+ compat fix) | Review now: homelab retired cAdvisor in July 2026 |
| `mcp-git` | Git MCP server with ssh deps + Docker secret injection | Review now: homelab retired the service in July 2026 |
| `mcp-auth-proxy` | OAuth proxy on Alpine runtime (homelab compose needs /bin/sh for secret-loading entrypoint) | Upstream ships an image with /bin/sh and `*_FILE` env-var support |
| `pr-reviewer` | AI PR reviewer with Claude/Gemini/Codex CLIs | Never (custom multi-model engine) |
| `semaphore` | Semaphore UI + homelab tools (sops, age, dig, jq, rsync) | Never (tooling layer always needed) |
| `dagu-ops` | Dagu + restic + rclone + Docker CLI | Never (ops tooling layer) |
| `docs-hub` | Starlight documentation aggregation, visual viewers, read-only API, and MCP | Never (custom application) |
| `mcp-reddit` | Custom Reddit search server backed by SearXNG and archives | Reddit restores viable personal API access |
| `mcp-substack` | Custom MCP server for authenticated Substack content | Never (custom server) |
| `miniflux-enricher` | Custom translation and de-SEO webhook worker | Review now: homelab decommissioned it in July 2026 |
| `pihole-exporter` | Upstream exporter wrapped for Docker secret injection | When upstream supports file-based secret ingestion |

## MCP Service Images

16 containerized MCP servers driven by [`mcp-images.json`](mcp-images.json). All follow the same pattern:
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

Conventions (no `.ci.json` needed): platforms=linux/amd64+linux/arm64,
tag=latest, no tests.

## CI & Automation

| Workflow | Trigger | What |
|----------|---------|------|
| **Build** | Push to main, PRs, dispatch | Auto-discover + matrix build, test, push to GHCR; gitleaks scan on PRs |
| **Lint** | Push, PRs | ruff, shellcheck, hadolint, actionlint, yamllint, zizmor, lychee |
| **Maintenance** | Weekly, dispatch | Trivy vuln scan, dockle CIS scan |
| **Mirror base images** | Weekly, dispatch | Mirrors Docker Hub base images to GHCR |

Base images mirrored to `ghcr.io/alxleo/base-images/` -- zero Docker Hub dependency for builds.

## Testing

| Suite | What | Trigger |
|-------|------|---------|
| Per-image tests | `.ci.json` `test_commands` (smoke tests, pytest) | Image changes |
| Caddy routing E2E | Snippet imports, handle_path, redirects | caddy-cloudflare changes |
| MCP E2E stack | Full Caddy -> mcp-proxy -> MCP server chain | MCP or caddy changes |
| MCP smoke | Standalone health + MCP initialize | MCP canaries (npm + Python) |

Run the fast local preflight before pushing:

```bash
just check
```

Build and exercise one custom image with the same `.ci.json` test commands CI
uses, or one shared MCP image from `mcp-images.json`:

```bash
just test-image mcp-auth-proxy
just test-image mcp-hackernews
```

Credential-free shared MCP images get a live initialize + `tools/list` smoke
test. Secret-bearing images are built without starting by default; a manifest
may declare obvious non-secret `smoke_env` fixtures when the server can safely
initialize without contacting its upstream provider. Pull-request CI runs the
same declared image checks and protocol smoke tests against the exact image it
just built. MCPJam remains useful as an independent local or deployed protocol
doctor when a server needs interactive inspection.

Smokeable MCP images may also declare a checked-in `contract`. The exact-image
test then requires the normalized tool names and input-schema hashes to match.
Verify the same lock against any Streamable HTTP endpoint, including a ToolHive
replacement:

```bash
python3 scripts/mcp-contract.py \
  --url http://127.0.0.1:8080/mcp \
  --verify mcp-contracts/mcp-hackernews.json
```

Capture a reviewed baseline with `--capture <path>`. MCPJam's CLI is the
independent protocol oracle (`server doctor`, `tools list`, and harmless
`tools call`); the checked-in normalizer remains deterministic and dependency
free.

Local prerequisites are Docker, `just`, `jq`, `uv`, and `conftest`. Targeted
image tests may require additional tools named by their test commands (for
example npm or ripgrep). CI-only `test_setup` commands are not run locally.
