#!/usr/bin/env bash
# Start an exact local MCP image and prove its HTTP protocol contract.
set -euo pipefail

IMAGE_NAME="${1:?Usage: $0 <image-name> <image-ref> <host-port> [ENV=VALUE ...]}"
IMAGE_REF="${2:?Usage: $0 <image-name> <image-ref> <host-port> [ENV=VALUE ...]}"
HOST_PORT="${3:?Usage: $0 <image-name> <image-ref> <host-port> [ENV=VALUE ...]}"
shift 3

CONTAINER="${IMAGE_NAME}-contract-${RANDOM}-$$"

cleanup() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker_args=(
    run
    -d
    --name "$CONTAINER"
    -e MCP_STARTUP_JITTER=0
    -p "127.0.0.1:${HOST_PORT}:8080"
)

for env_pair in "$@"; do
    if [[ ! "$env_pair" =~ ^[A-Za-z_][A-Za-z0-9_]*=.+$ ]]; then
        echo "ERROR: invalid smoke environment assignment: $env_pair" >&2
        exit 2
    fi
    docker_args+=(-e "$env_pair")
done

docker "${docker_args[@]}" "$IMAGE_REF" >/dev/null
bash "$(dirname "$0")/test-mcp-smoke.sh" "$CONTAINER" "$HOST_PORT"
