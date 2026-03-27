#!/usr/bin/env bash
# Mirror Docker Hub base images to GHCR to avoid rate limits.
#
# Usage: ./scripts/mirror-base-images.sh [--check]
#
# Without args: mirrors all base images found in Dockerfiles to GHCR.
# With --check: verifies mirrors exist without copying (for CI drift detection).
#
# Requires: docker (with buildx), gh (for GHCR auth)
# Image list is extracted from Dockerfiles — no hardcoded list to maintain.
# Only copies linux/amd64 + linux/arm64 (CI runners + Mac).

set -euo pipefail

DEST_PREFIX="ghcr.io/alxleo/base-images"
PLATFORMS="linux/amd64,linux/arm64"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_ONLY=false

if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=true
fi

# Extract unique Docker Hub base images from all Dockerfiles
images=()
while IFS= read -r img; do
    images+=("$img")
done < <(
    grep -rh "^FROM ghcr.io/alxleo/base-images/" "$REPO_ROOT"/*/Dockerfile* 2>/dev/null |
    sed 's/^FROM //' | sed 's/ AS .*//' |
    sed "s|ghcr.io/alxleo/base-images/||" |
    sort -u
)

if [[ ${#images[@]} -eq 0 ]]; then
    echo "No GHCR base-images references found in Dockerfiles"
    exit 0
fi

echo "Found ${#images[@]} base images in Dockerfiles:"
printf '  %s\n' "${images[@]}"
echo ""

if $CHECK_ONLY; then
    # Verify each mirror exists on GHCR
    missing=0
    for name in "${images[@]}"; do
        if docker buildx imagetools inspect "${DEST_PREFIX}/${name}" &>/dev/null; then
            echo "  ✓ ${name}"
        else
            echo "  ✗ ${name} — MISSING from GHCR"
            missing=$((missing + 1))
        fi
    done
    if [[ $missing -gt 0 ]]; then
        echo ""
        echo "ERROR: ${missing} image(s) missing. Run: ./scripts/mirror-base-images.sh"
        exit 1
    fi
    echo ""
    echo "All mirrors present."
    exit 0
fi

# Ensure GHCR login — CI uses GITHUB_TOKEN, local uses gh CLI
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
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
