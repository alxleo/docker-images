#!/bin/sh
# Load Docker secrets into environment variables.
# None are required today (Arctic-Shift needs no credentials); kept for
# parity with the fleet entrypoint pattern and graceful handling of stale
# compose files that still mount the old OAuth secrets.
for f in /run/secrets/*; do
    [ -f "$f" ] || continue
    varname=$(basename "$f" | tr '[:lower:]' '[:upper:]')
    export "$varname"="$(cat "$f")"
done

echo "=== mcp-reddit (arctic-shift backend) starting ==="
echo "Port: ${MCP_PORT:-8080}"
echo "==="

exec mcp-proxy --port "${MCP_PORT:-8080}" --shell "python /app/server.py"
