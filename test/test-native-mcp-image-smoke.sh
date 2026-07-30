#!/usr/bin/env bash
# Verify that a native Streamable HTTP image becomes ready and matches its tool contract.

set -euo pipefail

CONTAINER="${1:?Usage: $0 <container-name> <port> <contract-lock>}"
PORT="${2:?Usage: $0 <container-name> <port> <contract-lock>}"
CONTRACT_LOCK="${3:?Usage: $0 <container-name> <port> <contract-lock>}"
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
URL="http://127.0.0.1:${PORT}/mcp"

if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]]; then
    echo "FAIL: container is not running: ${CONTAINER}" >&2
    exit 1
fi

echo "Waiting for native MCP contract..."
for _ in $(seq 1 60); do
    if python3 "${ROOT}/scripts/mcp-contract.py" \
        --url "$URL" --verify "$CONTRACT_LOCK" >/dev/null 2>&1; then
        python3 "${ROOT}/scripts/mcp-contract.py" \
            --url "$URL" --verify "$CONTRACT_LOCK"
        echo "PASS: native MCP endpoint is ready"
        exit 0
    fi
    sleep 1
done

echo "FAIL: native MCP contract did not become ready (60s timeout)" >&2
docker logs "$CONTAINER" 2>&1 | tail -30 >&2
exit 1
