# Changelog

## [1.1.0](https://github.com/alxleo/docker-images/compare/mcp/v1.0.0...mcp/v1.1.0) (2026-03-28)


### Features

* initial images — Caddy, cAdvisor, 14 MCP servers, CI pipeline ([d06b7ea](https://github.com/alxleo/docker-images/commit/d06b7ea6a5de57e423f6460ae863e2cc16277658))
* unit tests for entrypoint.py and manifest validation ([#30](https://github.com/alxleo/docker-images/issues/30)) ([eab68d1](https://github.com/alxleo/docker-images/commit/eab68d1e4e93196f4300627a9e4860f8e5fbbee0))


### Bug Fixes

* add OCI source labels to all Dockerfiles ([#81](https://github.com/alxleo/docker-images/issues/81)) ([3bf3571](https://github.com/alxleo/docker-images/commit/3bf35716729caf2c0fe11d41014d78aeb5b5fdd5))
* remove internal deployment details from comments ([#18](https://github.com/alxleo/docker-images/issues/18)) ([1cc4839](https://github.com/alxleo/docker-images/commit/1cc48395d3d1b142704a8240c27a81d76ed9740f))
* resolve all zizmor and hadolint lint suppressions ([#16](https://github.com/alxleo/docker-images/issues/16)) ([8f907f0](https://github.com/alxleo/docker-images/commit/8f907f0055f6011a013af315da60a3e5989c3295))
* use GCR mirror to avoid Docker Hub rate limits in CI ([#75](https://github.com/alxleo/docker-images/issues/75)) ([7d8453e](https://github.com/alxleo/docker-images/commit/7d8453e14f5d5fae3631aacd4a81fe17da59265e))
