# docker-images

Pre-built Docker images for self-hosted services. Published to `ghcr.io/alxleo/`.

## Custom Images

Auto-discovered from `*/Dockerfile`. Per-image config in optional `.ci.json` files.

| Image | Why | Remove when |
|-------|-----|-------------|
| `caddy-cloudflare` | Caddy + Cloudflare DNS + docker-proxy + Sablier plugins | Never (plugins aren't in upstream) |
| `mcp-auth-proxy` | OAuth proxy on Alpine runtime (homelab compose needs /bin/sh for secret-loading entrypoint) | Upstream ships an image with /bin/sh and `*_FILE` env-var support |
| `dagu-ops` | Dagu + restic + rclone + Docker CLI | Never (ops tooling layer) |
| `docs-hub` | Starlight documentation aggregation, visual viewers, read-only API, and MCP | Never (custom application) |
| `gitea-ci-runner` | Pinned Python, Node, lint, Kubernetes, Windmill, and automation CLIs for Gitea Actions | When the homelab workflows no longer need a shared job image |
| `mcp-reddit` | Custom Reddit search server backed by SearXNG and archives | Reddit restores viable personal API access |
| `finrobot-mcp` | FinRobot V2 API plus a restricted OpenAPI MCP facade | FinRobot V2 ships a supported MCP server |
| `mcp-openbb` | OpenBB native Streamable HTTP MCP with SEC, FRED, ECB, IMF, CBOE, Nasdaq, and BLS extensions | OpenBB ships a native image with the same policy controls |
| `pihole-exporter` | Upstream exporter wrapped for Docker secret injection | When upstream supports file-based secret ingestion |
| `windmill-deploy-worker` | Windmill worker with browser verifier, sync CLI, mise, coolify-cli, compose CLI baked in | Windmill workers gain runtime package install |

## MCP Service Images

14 containerized MCP servers driven by [`mcp-images.json`](mcp-images.json).
The shared legacy images follow this pattern:
- npm-based: `mcp/Dockerfile.npm` | Python-based: `mcp/Dockerfile.python`
- Shared `mcp/entrypoint.py` handles mcp-proxy startup, tool filtering, and secret injection
- Health: `GET /ping` on port `8080` (from `mcp-proxy`, validated by CI)

Custom servers can instead expose native Streamable HTTP. `mcp-reddit` does so
on `/mcp`, with protocol-aware image tests and no Node.js proxy or filter
packages.

`mcp-openbb` runs the upstream `openbb-mcp` launcher on port `8080` at `/mcp`.
It pins OpenBB Core 2.0.1, MCP Server 2.0.1, SEC/FRED/ECB/CBOE/Nasdaq/BLS
2.0.0, and IMF 3.0.0. The runtime allow-list is
`bls,cboe,ecb,fred,imf,nasdaq,sec`; CLI tools, bundled skills,
`run_pipeline`, and `install_skill` are disabled. OpenBB state lives under
`/home/app/.openbb_platform`; `/cache`, `/data`, and `/tmp` are writable for
runtime mounts. CBOE and Nasdaq use OpenBB's native
`preferences.cache_directory` setting and write their SQLite response caches
under `/cache/http`; BLS metadata is shipped in the package and its request
memoization is in memory. The default image settings point
`cache_directory` to `/cache` and `data_directory` to `/data`; homelab may
project `user_settings.json` at `/home/app/.openbb_platform/user_settings.json`
with the same preferences plus provider credentials. Credentials and provider
settings belong in homelab-projected files rather than the image.
The pinned BLS 2.0.0 series fetcher inherits mandatory credential validation,
despite upstream documentation describing the key as optional. Keyless metadata
search works; series retrieval needs a BLS key or a supported upstream fix.

`finrobot-mcp` uses the FinRobot V2 source at commit
`2717499b8e30f242640af08c4ad9afd1113c2d45`. Run the same image with `api` for
the native `finrobot.server:app` on port `8000`, or `mcp` for the thin FastMCP
OpenAPI facade on port `8080` at `/mcp`. FinRobot dependencies use constraints
exported from that commit's frozen upstream lockfile. Its allow-list contains compute POSTs,
run creation/status reads, and artifact reads; settings, secrets, chat,
coverage mutations, cancellation, deletion, and viewed-state writes are
excluded. `runs_create` starts persistent research and LLM/provider work;
callers must be trusted and deployment must limit the model consumer's scope
and budget. `FINROBOT_API_URL` selects the API endpoint and
`FINROBOT_CAPABILITY_TOKEN` is forwarded as `Authorization: Bearer ...` and
`FINROBOT_API_HOST_HEADER` defaults to `127.0.0.1` for FinRobot's host allow-list.
FinRobot state persists under `/home/app/.finrobot`, with
`FINROBOT_CACHE_DB_PATH` defaulting to `/cache/finrobot/data_cache.db`; mount
`.secrets` and `settings.json` there from homelab infrastructure.

## ToolHive MCP Fleet

[`mcp-fleet.json`](mcp-fleet.json) is the forward runtime catalog for all 17
repository MCPs. It pins ToolHive, MCPJam, Node 26, Python 3.14, packages,
ports, secret references, networks, mounts, and removal criteria for the two
workloads that still depend on a legacy wrapper. Homelab can consume this
catalog without inheriting image-generation or tool-filter logic; it remains
responsible for secret values, host paths, Docker networks, supervision, and
gateway exposure.

Hacker News and Sequential Thinking run directly from their pinned upstream
packages through ToolHive. Their contracts remain here as runtime acceptance
oracles, but this repository no longer publishes wrapper images for them.

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
just test-toolhive-fleet replacements  # Hacker News + Sequential Thinking only
```

The live test runs the pinned Hacker News and Sequential Thinking packages on
Node 26 and Arxiv on Python 3.14 through ToolHive, then connects Jina through
ToolHive's native remote transport. It verifies their complete 11-, 1-, 19-,
and 21-tool contracts, makes harmless calls against both retired-image
replacements, and checks every handshake independently with MCPJam. The Hacker
News lane also proves that an allow-list hides and rejects a blocked tool. It
uses an isolated temporary ToolHive state directory and removes only its
uniquely named test workloads.

MCPJam 5.3.0's `server probe` passes this endpoint. Its higher-level
`server doctor` and `tools list` currently time out during version negotiation
against ToolHive even though the initialize probe and deterministic
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
just test-image mcp-context7
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
