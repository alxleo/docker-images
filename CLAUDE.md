# THIS IS A PUBLIC REPOSITORY

Everything committed here is visible to the entire internet.

NEVER commit: secrets, API keys, tokens, passwords, internal IPs, private hostnames,
SOPS-encrypted files, .env files, or anything from private repositories.

This repo contains ONLY: Dockerfiles, entrypoint scripts, build configs, CI workflows, and E2E tests.

## Image Types

| Type | Pattern | Example |
|------|---------|---------|
| **MCP images** (matrix) | `mcp-images.json` → `Dockerfile.npm` or `Dockerfile.python` | mcp-reddit, mcp-arxiv |
| **Patched upstream** | `git clone --tag` + `sed` fix + build | mcp-auth-proxy (VARCHAR fix), cadvisor (Docker 29 compat) |
| **Custom build** | Standard Dockerfile | caddy-cloudflare (xcaddy + DNS plugin), git-mcp-server |

## Patched Upstream Pattern

When upstream has a bug, don't maintain a full fork. Clone at a pinned tag and apply a minimal fix:

```dockerfile
RUN git clone --branch v2.5.3 --depth 1 https://github.com/upstream/repo.git .
RUN sed -i 's/broken/fixed/g' path/to/file.go   # link to upstream issue
RUN go build ...
```

Each patched Dockerfile has a header comment with: upstream repo, issue link, what's fixed, and when to remove (upstream merges the fix → delete sed line → switch back to upstream image).

## Caddy E2E Tests

`test/` contains a compose stack that validates Caddy routing patterns before deploy:
- `docker-compose.test.yml` — Caddy + echo service
- `Caddyfile.test` — exercises snippets, handle_path, handle mutual exclusivity
- `test-caddy-routing.sh` — 5 checks (routes, health, prefix strip, redirect fallback)

GHA runs `caddy validate` + the E2E suite on every push and PR. Pre-commit runs `caddy fmt --diff`.
