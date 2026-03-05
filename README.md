# docker-images

Pre-built Docker images for self-hosted services where upstream images are broken, stale, or missing needed plugins.

## Images

| Image | Why | Remove when |
|-------|-----|-------------|
| `ghcr.io/alxleo/caddy-cloudflare:2.11` | Caddy + Cloudflare DNS plugin for ACME DNS-01 challenges | Never (plugin isn't in upstream Caddy) |
| `ghcr.io/alxleo/cadvisor:v0.56.2` | cAdvisor built from source — upstream stuck at v0.53.0 which crashes with Docker 29+ | ghcr.io publishes v0.57+ |

## MCP Service Images

Pre-built MCP (Model Context Protocol) server images. Each wraps a specific MCP package with mcp-proxy for HTTP transport.

Image list is driven by [`mcp-images.json`](mcp-images.json). All images follow the same pattern:
- npm-based: `mcp/Dockerfile.npm` — installs npm package globally at build time
- Python-based: `mcp/Dockerfile.python` — installs via `uv pip install --system`
- Shared `mcp/entrypoint.py` handles mcp-proxy startup, tool filtering, and secret injection

| Image | Package | Tag |
|-------|---------|-----|
| `ghcr.io/alxleo/mcp-hackernews` | `mcp-hacker-news` | 1.0.3 |
| `ghcr.io/alxleo/mcp-reddit` | `reddit-mcp-server` | 1.3.2 |
| `ghcr.io/alxleo/mcp-brave` | `brave-search-mcp` | 2.0.1 |
| `ghcr.io/alxleo/mcp-slack` | `slack-mcp-server` | 1.1.28 |
| `ghcr.io/alxleo/mcp-tavily` | `tavily-mcp` | 0.2.17 |
| `ghcr.io/alxleo/mcp-context7` | `@upstash/context7-mcp` | 2.1.1 |
| `ghcr.io/alxleo/mcp-sequential-thinking` | `@modelcontextprotocol/server-sequential-thinking` | 2025.12.18 |
| `ghcr.io/alxleo/mcp-firecrawl` | `firecrawl-mcp` | 3.9.0 |
| `ghcr.io/alxleo/mcp-jina` | `mcp-remote` | 0.1.38 |
| `ghcr.io/alxleo/mcp-confluence` | `@aashari/mcp-server-atlassian-confluence` | 3.3.0 |
| `ghcr.io/alxleo/mcp-jira` | `@aashari/mcp-server-atlassian-jira` | 3.3.0 |
| `ghcr.io/alxleo/mcp-youtube` | `mcp-youtube-transcript` | 0.5.9 |
| `ghcr.io/alxleo/mcp-arxiv` | `arxiv-mcp-server` | 0.3.2 |
| `ghcr.io/alxleo/mcp-zen` | `zen-mcp-server` | 7afc7c1 |

### Health Endpoint

All MCP images expose a health endpoint provided by `mcp-proxy`. Runtime defaults are in [`mcp-defaults.json`](mcp-defaults.json) — downstream repos should read from there instead of hardcoding values.

| | |
|---|---|
| **Path** | `GET /ping` |
| **Response** | `200 "pong"` |
| **Port** | `8080` |
| **Provided by** | `mcp-proxy` (hardcoded, not configurable) |

Use `/ping` for Docker Compose healthchecks, Caddy `health_uri`, and monitoring. CI validates this contract on every change via the E2E stack test.

## Deployment Examples

[`examples/`](examples/) contains reference deployment patterns:

- **`docker-compose.yml`** — Hardened MCP service deployment with read-only filesystem, capability dropping, resource limits, healthchecks, Docker secrets, and tool filtering
- **`Caddyfile.mcp-routing`** — Caddy reverse proxy patterns for MCP services: `handle_path` prefix stripping, `flush_interval -1` for SSE, CORS, Chrome Private Network Access preflight, service discovery

## Testing

| Suite | What it validates | Trigger |
|-------|-------------------|---------|
| **Caddy routing** (`test/test-caddy-routing.sh`) | Snippet imports, handle_path, redirect fallback | caddy-cloudflare changes |
| **MCP E2E stack** (`test/test_mcp_stack.py`) | Full Caddy → mcp-proxy → MCP server chain with both npm and Python canaries: health contract, MCP protocol, routing, TLS, service discovery | caddy-cloudflare or mcp changes |
| **MCP smoke** (`test/test-mcp-smoke.sh`) | Standalone mcp-proxy health + MCP initialize + tools/list | mcp changes (2 canaries: npm + Python) |

The E2E stack test (pytest) spins up a Docker Compose stack with Caddy + both canary types (hackernews/npm, arxiv/Python) and runs a full contract validation battery. This is the test that downstream repos depend on.

Run locally:
```bash
# Full-stack E2E (Caddy + both MCP canaries)
pip install -r test/requirements.txt
python -m pytest test/test_mcp_stack.py -v

# Standalone smoke test
docker build -f mcp/Dockerfile.npm --build-arg MCP_PACKAGE="mcp-hacker-news@1.0.3" -t test-hn mcp/
docker run -d --name test-hn -e MCP_STARTUP_JITTER=0 -p 8080:8080 test-hn
bash test/test-mcp-smoke.sh test-hn 8080
docker rm -f test-hn
```

## How it works

GitHub Actions builds and pushes images to ghcr.io on push to `main`. Images are public — no auth needed to pull.

Manual trigger: Actions tab → Build Custom Images → Run workflow.
