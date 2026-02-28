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

## Tests

`test/` contains three test suites:

**Caddy routing** (`test-caddy-routing.sh`): Validates Caddy config patterns (snippets, handle_path, handle mutual exclusivity). Compose: `docker-compose.test.yml` + `Caddyfile.test`. 5 curl-based checks.

**MCP E2E** (`test-mcp-e2e.sh`): Full-stack Caddy → mcp-proxy → MCP server validation. Compose: `docker-compose.mcp-e2e.yml` + `Caddyfile.mcp-e2e`. Tests: prefix stripping, MCP protocol handshake (initialize + tools/list), session header passthrough, TLS with internal certs, service discovery.

**MCP smoke** (`test-mcp-smoke.sh`): Standalone MCP image validation (no Caddy). Tests: container health via `/ping`, MCP initialize handshake, tools/list. Takes container name and port as args. CI runs 2 canaries: mcp-hackernews (npm) + mcp-arxiv (Python).

MCP protocol testing works without API keys — initialize and tools/list succeed without auth. Only tools/call needs keys.

Pre-commit runs `caddy fmt --diff`. GHA runs `caddy validate` + all three suites.

## CI & Automation

This repo is fully automated — there are no manual build or deploy steps.

- **Pre-commit hooks** (`.pre-commit-config.yaml`): gitleaks, shellcheck, hadolint, actionlint, yamllint, zizmor, secret file blocking, caddy fmt. These run locally on every commit — catch issues before pushing.
- **Lint workflow** (`.github/workflows/lint.yml`): same linters as pre-commit plus lychee link checker. Runs on all PRs and pushes to main as a safety net.
- **Build workflow** (`.github/workflows/build-images.yml`): builds only changed images on PR (no push), builds + pushes to ghcr.io on merge to main. Change detection via `dorny/paths-filter` — unchanged images are skipped to avoid unnecessary pulls downstream. **Bot PRs (Dependabot, etc.) skip image builds** — only lint runs, saving CI minutes.
- **Trivy CVE scanning**: every built image is scanned for CRITICAL vulnerabilities before push. Uses `ignore-unfixed: true` to skip base-image CVEs without patches (see workflow header comments for specific CVEs and revisit timeline).
- **Dependabot** (`.github/dependabot.yml`): weekly PRs for GHA action versions and base image updates — manual review required, no auto-merge
- **Branch ruleset**: main requires PRs, force push blocked

Do NOT add `justfile`, `Makefile`, or wrapper scripts — there are no manual commands to automate. If you need to test a build locally, just `docker build` the relevant directory.

## Development Workflow

All changes go through PRs. The standard loop:

1. Create a branch, make changes, commit (pre-commit hooks run locally)
2. Push branch, open PR
3. Watch CI: `gh pr checks <number> --watch`
4. Check for reviewer comments (Codex auto-reviews): `gh pr view <number> --comments`
5. Fix any failures or address feedback, push again
6. Repeat 3-4 until all checks pass and feedback is addressed
7. Merge

This push → watch → fix loop is the defacto workflow. No manual builds, no local Docker required for CI — GitHub Actions handles everything.
