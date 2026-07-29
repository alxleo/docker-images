#!/usr/bin/env bash
# Build one auto-discovered custom image and run its CI test commands locally.

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: scripts/test-image.sh <image-name-or-context>

Examples:
  scripts/test-image.sh mcp-auth-proxy
  scripts/test-image.sh git-mcp-server
EOF
}

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

for command_name in docker jq; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $command_name" >&2
        exit 1
    fi
done

requested_image="$1"
matrix="$(bash "$repo_root/scripts/discover-images.sh")"
match_count="$(
    jq --arg requested "$requested_image" \
        '[.[] | select(.name == $requested or .context == $requested)] | length' \
        <<<"$matrix"
)"

if [[ "$match_count" -ne 1 ]]; then
    echo "ERROR: expected one image named or contextualized as '$requested_image'; found $match_count" >&2
    echo "Available images:" >&2
    jq -r '.[] | "  \(.name) (context: \(.context))"' <<<"$matrix" >&2
    exit 1
fi

entry="$(
    jq -c --arg requested "$requested_image" \
        '.[] | select(.name == $requested or .context == $requested)' \
        <<<"$matrix"
)"
image_name="$(jq -r '.name' <<<"$entry")"
image_context="$(jq -r '.context' <<<"$entry")"
image_tag="$(jq -r '.tag' <<<"$entry")"
configured_platforms="$(jq -r '.platforms' <<<"$entry")"
build_args="$(jq -r '.build_args' <<<"$entry")"
test_commands="$(jq -c '.test_commands' <<<"$entry")"

docker_arch="$(docker info --format '{{.Architecture}}')"
case "$docker_arch" in
    amd64 | x86_64)
        native_platform="linux/amd64"
        ;;
    arm64 | aarch64)
        native_platform="linux/arm64"
        ;;
    *)
        echo "ERROR: unsupported Docker architecture: $docker_arch" >&2
        exit 1
        ;;
esac

if [[ "$configured_platforms" == *","* ]]; then
    build_platform="$native_platform"
elif [[ "$configured_platforms" == "$native_platform" ]]; then
    build_platform="$configured_platforms"
else
    build_platform="$configured_platforms"
    echo "NOTE: image is configured only for $build_platform; cross-building on $native_platform" >&2
fi

image_ref="docker-images-local/${image_name}:${image_tag}"
build_command=(
    docker buildx build
    --load
    --platform "$build_platform"
    --tag "$image_ref"
)

while IFS= read -r build_arg; do
    if [[ -n "$build_arg" ]]; then
        build_command+=(--build-arg "$build_arg")
    fi
done <<<"$build_args"

build_command+=("$repo_root/$image_context")

echo "==> Building $image_name as $image_ref ($build_platform)"
"${build_command[@]}"

export GITHUB_WORKSPACE="$repo_root"
export IMAGE_NAME="$image_name"
export IMAGE_REF="$image_ref"

test_count="$(jq 'length' <<<"$test_commands")"
if [[ "$test_count" -eq 0 ]]; then
    echo "==> No test_commands configured for $image_name"
    exit 0
fi

echo "==> Running $test_count configured test command(s)"
rendered_test_commands="$(jq -r '.[]' <<<"$test_commands")"
while IFS= read -r test_command; do
    echo "==> $test_command"
    (
        cd "$repo_root"
        bash -euo pipefail -c "$test_command"
    )
done <<<"$rendered_test_commands"
