# docker-images

Pre-built Docker images for self-hosted services. Published to `ghcr.io/alxleo/`.

## Custom Images

Auto-discovered from `*/Dockerfile`. Per-image config in optional `.ci.json` files.

| Image | Why | Remove when |
|-------|-----|-------------|
| `caddy-cloudflare` | Caddy + Cloudflare DNS + docker-proxy + tailscale plugins | Never (plugins aren't in upstream) |
| `mcp-auth-proxy` | OAuth proxy on Alpine runtime (homelab compose needs /bin/sh for secret-loading entrypoint) | Upstream ships an image with /bin/sh and `*_FILE` env-var support |
| `pr-reviewer` | AI PR reviewer with Claude/Gemini/Codex CLIs | Never (custom multi-model engine) |
| `dagu-ops` | Dagu + restic + rclone + Docker CLI | Never (ops tooling layer) |
| `docs-hub` | Starlight documentation aggregation, visual viewers, read-only API, and MCP | Never (custom application) |
| `mcp-reddit` | Custom Reddit search server backed by SearXNG and archives | Reddit restores viable personal API access |
| `mcp-substack` | Custom MCP server for authenticated Substack content | Never (custom server) |
| `pihole-exporter` | Upstream exporter wrapped for Docker secret injection | When upstream supports file-based secret ingestion |

## MCP Service Images

16 containerized MCP servers driven by [`mcp-images.json`](mcp-images.json).
The shared legacy images follow this pattern:
- npm-based: `mcp/Dockerfile.npm` | Python-based: `mcp/Dockerfile.python`
- Shared `mcp/entrypoint.py` handles mcp-proxy startup, tool filtering, and secret injection
- Health: `GET /ping` on port `8080` (from `mcp-proxy`, validated by CI)

Custom servers can instead expose native Streamable HTTP. `mcp-reddit` and
`mcp-substack` do so on `/mcp`, with protocol-aware image tests and no Node.js
proxy or filter packages.

## ToolHive MCP Fleet

[`mcp-fleet.json`](mcp-fleet.json) is the forward runtime catalog for all 18
repository MCPs. It pins ToolHive, MCPJam, Node 26, Python 3.14, packages,
ports, secret references, networks, mounts, and removal criteria for the three
workloads that still depend on a legacy wrapper. Homelab can consume this
catalog without inheriting image-generation or tool-filter logic; it remains
responsible for secret values, host paths, Docker networks, supervision, and
gateway exposure.

Secret-bearing plans use ToolHive's read-only environment provider. Consumers
set `TOOLHIVE_SECRETS_PROVIDER=environment` and expose only the named
`TOOLHIVE_SECRET_*` variables to the ToolHive process; the catalog and rendered
plan contain references, never values.

Where a reviewed contract lock exists, its tool names are also the fleet's
explicit ToolHive allow-list. Changing the exposed surface therefore requires
one reviewable change to both the lock and catalog instead of an opaque
`FILTER_INCLUDE` or `FILTER_EXCLUDE` value inside a container.

Validate the catalog and render a consumer-neutral execution plan:

```bash
python3 scripts/toolhive-fleet.py validate
python3 scripts/toolhive-fleet.py plan
python3 scripts/toolhive-fleet.py endpoints
```

Local plans bind to loopback. A containerized gateway can render the same
fleet for its Docker bridge address with `--host`; non-loopback plans fail
closed unless at least one `--allowed-origin` is supplied.

Run the live Docker oracle with the exact pinned ToolHive binary:

```bash
just test-toolhive-fleet
```

The live test builds the pinned Hacker News package on Node 26 and Arxiv on
Python 3.14 through ToolHive, then connects Jina through ToolHive's native
remote transport. It verifies their complete 11-, 14-, and 21-tool contracts
and checks every handshake independently with MCPJam. The Hacker News lane also
proves that an allow-list hides and rejects a blocked tool. It uses an isolated
temporary ToolHive state directory and removes only its uniquely named test
workloads.

MCPJam 3.16.0's `server probe` passes this endpoint. Its higher-level
`server doctor` and `tools list` currently time out during version negotiation
against ToolHive 0.41.0 even though the initialize probe and deterministic
contract succeed. The client sends the draft `server/discover` request before
legacy initialization; older servers can leave it unanswered. Keep the
deterministic contract plus `server probe` as the fleet oracle until that
upstream negotiation gap is fixed; do not add a compatibility proxy.

Jina is direct-remote and no longer uses `mcp-remote`. Its ToolHive secret
`JINA_AUTHORIZATION` must contain the complete header value
(`Bearer <JINA_API_KEY>`), allowing ToolHive to inject it without putting the
credential in the catalog, command line, or persisted workload configuration.

## Adding a New Image

1. Create a directory with a `Dockerfile`
2. Push

That's it. The CI auto-discovers images from `*/Dockerfile`. Optional `.ci.json` for non-defaults:

```json
{
  "platforms": "linux/amd64,linux/arm64",
  "test_commands": ["docker run --rm $IMAGE_REF sh -c 'tool --version'"],
  "watch_paths": ["test/shared-tool-smoke.sh"]
}
```

Conventions (no `.ci.json` needed): platforms=linux/amd64+linux/arm64,
tag=latest, no tests. Use `watch_paths` for files outside the image context
whose changes require that image's build and tests.

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
