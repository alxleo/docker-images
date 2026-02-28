#!/usr/bin/env bash
# MCP image smoke test — validates entrypoint.py → mcp-proxy → MCP server chain
#
# Usage: ./test-mcp-smoke.sh <container-name> <port>
#
# Checks:
#   1. Container is running
#   2. GET /ping → 200 "pong" (mcp-proxy health)
#   3. POST /mcp initialize → JSON-RPC response with capabilities
#   4. POST /mcp tools/list → response with tools array
#
# Requires: curl, jq
# No API keys needed — initialize and tools/list work without authentication.
set -euo pipefail

CONTAINER="${1:?Usage: $0 <container-name> <port>}"
PORT="${2:?Usage: $0 <container-name> <port>}"
BASE="http://localhost:${PORT}"
FAIL=0

check() {
    local desc="$1"
    shift
    if "$@"; then
        echo "PASS: $desc"
    else
        echo "FAIL: $desc"
        FAIL=1
    fi
}

# --- Check 1: Container is running ---
RUNNING=$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null) || true
check "Container is running" test "$RUNNING" = "true"

# --- Check 2: Health endpoint ---
echo "Waiting for mcp-proxy to be ready..."
READY=false
for _ in $(seq 1 60); do
    if curl -sf "${BASE}/ping" >/dev/null 2>&1; then
        READY=true
        break
    fi
    sleep 1
done
if [[ "$READY" != "true" ]]; then
    echo "FAIL: mcp-proxy never became ready (60s timeout)"
    echo "Container logs:"
    docker logs "$CONTAINER" 2>&1 | tail -30
    exit 1
fi

PING_BODY=$(curl -sf "${BASE}/ping")
check "GET /ping returns pong" test "$PING_BODY" = "pong"

# Extract JSON from MCP response (handles both SSE and plain JSON)
# mcp-proxy returns text/event-stream with data: {json} lines
extract_json() {
    local raw="$1"
    local sse_json
    sse_json=$(echo "$raw" | grep '^data: ' | head -1 | sed 's/^data: //' || true)
    if [[ -n "$sse_json" ]] && echo "$sse_json" | jq -e . >/dev/null 2>&1; then
        echo "$sse_json"
        return
    fi
    if echo "$raw" | jq -e . >/dev/null 2>&1; then
        echo "$raw"
        return
    fi
    echo ""
}

# --- Check 3: MCP initialize handshake ---
RAW_INIT=$(curl -s -D /tmp/smoke-headers --max-time 10 -X POST "${BASE}/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "1.0"}
        }
    }' 2>/dev/null) || true

INIT_JSON=$(extract_json "$RAW_INIT")

if [[ -z "$INIT_JSON" ]]; then
    echo "FAIL: MCP initialize — no valid JSON (raw: ${RAW_INIT:0:300})"
    FAIL=1
else
    HAS_CAPABILITIES=$(echo "$INIT_JSON" | jq -r '.result.capabilities // empty' 2>/dev/null)
    check "MCP initialize returns capabilities" test -n "$HAS_CAPABILITIES"

    # Extract session ID from response headers
    SESSION_ID=$(grep -i 'mcp-session-id' /tmp/smoke-headers | awk '{print $2}' | tr -d '\r\n') || true

    if [[ -n "$SESSION_ID" ]]; then
        # Send initialized notification
        curl -s --max-time 10 -X POST "${BASE}/mcp" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            -H "Mcp-Session-Id: ${SESSION_ID}" \
            -d '{"jsonrpc": "2.0", "method": "notifications/initialized"}' >/dev/null 2>&1 || true

        # --- Check 4: tools/list ---
        RAW_TOOLS=$(curl -s --max-time 10 -X POST "${BASE}/mcp" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            -H "Mcp-Session-Id: ${SESSION_ID}" \
            -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}' 2>/dev/null) || true

        TOOLS_JSON=$(extract_json "$RAW_TOOLS")

        if [[ -n "$TOOLS_JSON" ]]; then
            TOOL_COUNT=$(echo "$TOOLS_JSON" | jq -r '.result.tools | length' 2>/dev/null)
            check "tools/list returns tools (count: ${TOOL_COUNT:-0})" test "${TOOL_COUNT:-0}" -gt 0
        else
            echo "FAIL: tools/list — no response"
            FAIL=1
        fi
    else
        echo "WARN: No Mcp-Session-Id header — skipping stateful tests (tools/list)"
        echo "  (Server may be running in stateless mode)"
    fi
fi

echo ""
if [[ "$FAIL" -eq 0 ]]; then
    echo "All smoke tests passed."
else
    echo "Some smoke tests FAILED."
    echo "Container logs:"
    docker logs "$CONTAINER" 2>&1 | tail -20
fi

exit $FAIL
