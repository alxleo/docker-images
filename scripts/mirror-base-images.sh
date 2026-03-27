#!/usr/bin/env bash
# Mirror Docker Hub base images to GHCR to avoid rate limits.
#
# Usage: ./scripts/mirror-base-images.sh
#
# Requires: docker (with buildx), gh (for GHCR auth)
# Run this when bumping base image versions in Dockerfiles.
#
# Only copies linux/amd64 + linux/arm64 (CI runners + Mac).
# Uses buildx imagetools — direct registry-to-registry, no local pull.

set -euo pipefail

DEST_PREFIX="ghcr.io/alxleo/base-images"
PLATFORMS="linux/amd64,linux/arm64"

images=(
    "alpine:3.23"
    "caddy:2.11"
    "caddy:2.11-builder"
    "debian:bookworm-slim"
    "golang:1.25-alpine"
    "golang:1.25-bookworm"
    "node:22-slim"
    "node:24-slim"
    "python:3.13-slim"
)

# Ensure GHCR login — CI uses GITHUB_TOKEN, local uses gh CLI
if [ -n "${GITHUB_TOKEN:-}" ]; then
    echo "${GITHUB_TOKEN}" | docker login ghcr.io -u "${GITHUB_ACTOR:-alxleo}" --password-stdin
else
    gh auth token | docker login ghcr.io -u alxleo --password-stdin
fi

for name in "${images[@]}"; do
    echo "=== ${name} ==="
    docker buildx imagetools create \
        --tag "${DEST_PREFIX}/${name}" \
        --platform "${PLATFORMS}" \
        "docker.io/library/${name}"
    echo ""
done

echo "Done. All base images mirrored to ${DEST_PREFIX}/"
