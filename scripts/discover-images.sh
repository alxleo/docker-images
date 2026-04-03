#!/usr/bin/env bash
# Discover custom Docker images by scanning for Dockerfiles.
#
# Convention: any directory with a Dockerfile is an image.
# Metadata: optional .ci.json per directory for non-default config.
#
# Defaults (no .ci.json needed):
#   platforms: linux/amd64,linux/arm64
#   tag: latest
#   test_setup: ""
#   test_commands: []
#
# Output: JSON array suitable for GitHub Actions matrix.

set -euo pipefail
shopt -s nullglob

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKIP_DIRS="^(mcp|test|scripts|\.github|\.claude)$"

images="[]"

for dockerfile in "$REPO_ROOT"/*/Dockerfile; do
    dir=$(dirname "$dockerfile")
    name=$(basename "$dir")

    # Skip non-image directories
    if echo "$name" | grep -qE "$SKIP_DIRS"; then
        continue
    fi

    # Read .ci.json if it exists, else empty object
    ci_json="{}"
    if [[ -f "$dir/.ci.json" ]]; then
        ci_json=$(cat "$dir/.ci.json")
    fi

    # Apply conventions + overrides from .ci.json
    # name override: allows image name to differ from directory (e.g. mcp-git in git-mcp-server/)
    image_name=$(echo "$ci_json" | jq -r --arg default "$name" '.name // $default')
    tag=$(echo "$ci_json" | jq -r '.tag // "latest"')
    platforms=$(echo "$ci_json" | jq -r '.platforms // "linux/amd64,linux/arm64"')
    test_setup=$(echo "$ci_json" | jq -r '.test_setup // ""')
    test_commands=$(echo "$ci_json" | jq -c '.test_commands // []')

    # Build matrix entry
    entry=$(jq -n \
        --arg name "$image_name" \
        --arg context "$(basename "$dir")" \
        --arg tag "$tag" \
        --arg platforms "$platforms" \
        --arg test_setup "$test_setup" \
        --argjson test_commands "$test_commands" \
        '{name: $name, context: $context, tag: $tag, platforms: $platforms, test_setup: $test_setup, test_commands: $test_commands}')

    images=$(echo "$images" | jq --argjson entry "$entry" '. + [$entry]')
done

echo "$images" | jq -c '.'
