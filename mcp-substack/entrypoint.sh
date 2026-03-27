#!/bin/sh
# Load Docker secrets into environment variables
for f in /run/secrets/*; do
    [ -f "$f" ] || continue
    varname=$(basename "$f" | tr '[:lower:]' '[:upper:]')
    export "$varname"="$(cat "$f")"
done

echo "=== mcp-substack starting ==="
echo "Port: ${MCP_PORT:-8080}"
echo "Username: ${SUBSTACK_USERNAME:-NOT SET}"
echo "Cookie: ${SUBSTACK_SID:+set (${#SUBSTACK_SID} chars)}"
echo "==="

exec mcp-proxy --port "${MCP_PORT:-8080}" --shell "python /app/server.py"
