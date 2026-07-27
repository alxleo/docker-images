# Docs Hub image

Astro Starlight documentation aggregator with an atomic mirror/build controller,
interactive visual viewers, a normalized read-only search API, and MCP tools.

The image is deliberately generic. It contains application code and owned visual
acceptance fixtures, but no deployment's repository manifest, visual policy,
credentials, hostnames, or source documents.

## Required runtime mounts

- `/config/sources.yml`: source IDs, Gitea `owner/repository`, branch, roots,
  include/exclude globs, label, and visual policy.
- `/config/visual-registry.yml`: enabled formats and their rendering, limits,
  CSP, fallback, and verifier policy.
- `/state`: persistent source snapshots and atomically published releases.
- `/run/secrets/docs_hub_gitea_token`: narrowly scoped mirror token in
  `controller` mode.
- `/run/secrets/docs_hub_api_token`: separate read-only bearer token in
  `machine` mode.

All locations can be changed with their corresponding `DOCS_HUB_*` environment
variables. Runtime defaults are localhost-safe:

```text
DOCS_HUB_CONFIG_ROOT=/config
DOCS_HUB_SITE_URL=http://localhost:8080
DOCS_HUB_ASSET_ORIGIN=http://localhost:8081
DOCS_HUB_GITEA_URL=http://localhost:3000
```

The image's final user is `1000:1000`. A deployment with a pre-created,
root-owned `/state` volume may start the container as root; the entrypoint only
changes ownership of `/state` and immediately drops to `1000:1000` with
`su-exec`.

## Execution boundary

Imported MDX imports/exports and components, script-bearing HTML, inline event
handlers, notebook cells, notebook HTML/JavaScript output, and repository
scripts are never executed. Only allowlisted `:::visual{...}` directives become
viewer components owned by the image. Standalone HTML is served from the
configured asset origin with a restrictive CSP and rendered in an empty
`sandbox` iframe.
