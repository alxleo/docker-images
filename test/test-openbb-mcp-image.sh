#!/usr/bin/env bash
set -euo pipefail

image="${OPENBB_MCP_TEST_IMAGE:?OPENBB_MCP_TEST_IMAGE is required}"
container="openbb-mcp-image-test"
port=18081
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$container" -p "${port}:8080" "$image" >/dev/null
ready=false
for _ in $(seq 1 90); do
    if docker exec "$container" /usr/local/bin/python /app/healthcheck.py >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
test "$ready" = true

docker exec -i -e PYTHONDONTWRITEBYTECODE=1 "$container" python - < test/test-openbb-provider-fixes.py

TEST_URL="http://127.0.0.1:${port}/mcp" python3 test/test-openbb-mcp-contract.py
