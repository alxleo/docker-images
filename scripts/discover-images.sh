#!/usr/bin/env bash
# Discover custom Docker images by scanning for Dockerfiles.
#
# Convention: any directory with a Dockerfile is an image.
# Metadata: optional .ci.json per directory for non-default config.
#
# Defaults (no .ci.json needed):
#   platforms: linux/amd64,linux/arm64
#   tag: latest
#   build_args: ""
#   watch_paths: []
#
# Tests: <dir>/test_<dir with - as _>.py, a pytest module run against the
# image just built (IMAGE_REF); see conftest.py at the repository root.
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
    # name override: allows the published image name to differ from its directory.
    image_name=$(echo "$ci_json" | jq -r --arg default "$name" '.name // $default')
    tag=$(echo "$ci_json" | jq -r '.tag // "latest"')
    platforms=$(echo "$ci_json" | jq -r '.platforms // "linux/amd64,linux/arm64"')
    build_args=$(echo "$ci_json" | jq -r '.build_args // ""')
    # Wrongly typed lists would make CI iterate nothing and pass; fail instead.
    watch_paths=$(echo "$ci_json" | jq -ce --arg f "$name/.ci.json" \
        '.watch_paths // [] | if type == "array" and all(type == "string") then . else error("\($f): watch_paths must be an array of strings") end')
    test_file="$name/test_${name//-/_}.py"
    if [[ ! -f "$REPO_ROOT/$test_file" ]]; then
        test_file=""
    fi

    # Build matrix entry
    entry=$(jq -n \
        --arg name "$image_name" \
        --arg context "$name" \
        --arg tag "$tag" \
        --arg platforms "$platforms" \
        --arg build_args "$build_args" \
        --arg test_file "$test_file" \
        --argjson watch_paths "$watch_paths" \
        '{name: $name, context: $context, tag: $tag, platforms: $platforms, build_args: $build_args, test_file: $test_file, watch_paths: $watch_paths}')

    images=$(echo "$images" | jq --argjson entry "$entry" '. + [$entry]')
done

echo "$images" | jq -c '.'
