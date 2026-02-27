# docker-images

Pre-built Docker images for homelab services where upstream images are broken, stale, or missing needed plugins.

## Images

| Image | Why | Remove when |
|-------|-----|-------------|
| `ghcr.io/alxleo/caddy-cloudflare:2.10` | Caddy + Cloudflare DNS plugin for ACME DNS-01 challenges | Never (plugin isn't in upstream Caddy) |
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

## How it works

GitHub Actions builds and pushes images to ghcr.io on push to `main`. Images are public — no auth needed to pull.

Manual trigger: Actions tab → Build Custom Images → Run workflow.
