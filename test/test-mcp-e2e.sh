#!/usr/bin/env bash
# MCP E2E test — validates full Caddy → mcp-proxy → MCP server chain
#
# Exercises: handle_path prefix stripping, reverse_proxy health_uri,
# flush_interval for SSE, MCP protocol handshake through proxy,
# TLS with internal certs, service discovery, session header passthrough.
#
# Requires: curl, jq
set -euo pipefail

HTTP_BASE="http://localhost:8080"
HTTPS_BASE="https://localhost:8443"
FAIL=0

check() {
    local desc="$1" url="$2" expect_code="$3" expect_body="${4:-}"
    local code body
    code=$(curl -sk -o /tmp/e2e-body -w '%{http_code}' --max-time 10 "$url")
    body=$(cat /tmp/e2e-body)
    if [[ "$code" != "$expect_code" ]]; then
        echo "FAIL: $desc — expected $expect_code, got $code (body: ${body:0:200})"
        FAIL=1
    elif [[ -n "$expect_body" && "$body" != *"$expect_body"* ]]; then
        echo "FAIL: $desc — body missing '$expect_body' (got: ${body:0:200})"
        FAIL=1
    else
        echo "PASS: $desc"
    fi
}

# Extract JSON from MCP response (handles both SSE and plain JSON)
# mcp-proxy returns text/event-stream with data: {json} lines
extract_json() {
    local raw="$1"
    # Try SSE format first: extract from "data: {...}" line
    local sse_json
    sse_json=$(echo "$raw" | grep '^data: ' | head -1 | sed 's/^data: //')
    if [[ -n "$sse_json" ]] && echo "$sse_json" | jq -e . >/dev/null 2>&1; then
        echo "$sse_json"
        return
    fi
    # Fall back to plain JSON
    if echo "$raw" | jq -e . >/dev/null 2>&1; then
        echo "$raw"
        return
    fi
    echo ""
}

check_mcp() {
    local desc="$1" base_url="$2"
    local raw_response init_json session_id raw_tools tools_json tool_count

    # Initialize — max-time prevents hang on open SSE stream
    raw_response=$(curl -sk -D /tmp/e2e-headers --max-time 10 \
        -X POST "${base_url}/hackernews/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "e2e-test", "version": "1.0"}
            }
        }' 2>/dev/null) || true

    init_json=$(extract_json "$raw_response")

    if [[ -z "$init_json" ]]; then
        echo "FAIL: ${desc} initialize — no valid JSON (raw: ${raw_response:0:300})"
        FAIL=1
        return
    fi

    local has_caps
    has_caps=$(echo "$init_json" | jq -r '.result.capabilities // empty' 2>/dev/null)
    if [[ -z "$has_caps" ]]; then
        echo "FAIL: ${desc} initialize — no capabilities (json: ${init_json:0:300})"
        FAIL=1
        return
    fi
    echo "PASS: ${desc} initialize returns capabilities"

    # Extract session ID from response headers
    session_id=$(grep -i 'mcp-session-id' /tmp/e2e-headers | awk '{print $2}' | tr -d '\r\n') || true

    if [[ -z "$session_id" ]]; then
        echo "WARN: ${desc} — no Mcp-Session-Id, skipping tools/list"
        return
    fi
    echo "PASS: ${desc} session header present"

    # Send initialized notification
    curl -sk --max-time 10 -X POST "${base_url}/hackernews/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "Mcp-Session-Id: ${session_id}" \
        -d '{"jsonrpc": "2.0", "method": "notifications/initialized"}' >/dev/null 2>&1 || true

    # tools/list
    raw_tools=$(curl -sk --max-time 10 -X POST "${base_url}/hackernews/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "Mcp-Session-Id: ${session_id}" \
        -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}' 2>/dev/null) || true

    tools_json=$(extract_json "$raw_tools")

    if [[ -n "$tools_json" ]]; then
        tool_count=$(echo "$tools_json" | jq -r '.result.tools | length' 2>/dev/null)
        if [[ "${tool_count:-0}" -gt 0 ]]; then
            echo "PASS: ${desc} tools/list returns ${tool_count} tools"
        else
            echo "FAIL: ${desc} tools/list — no tools (json: ${tools_json:0:200})"
            FAIL=1
        fi
    else
        echo "FAIL: ${desc} tools/list — no response"
        FAIL=1
    fi
}

# --- Wait for Caddy ---
echo "Waiting for Caddy..."
for _ in $(seq 1 60); do
    curl -sf "${HTTP_BASE}/health" >/dev/null 2>&1 && break
    sleep 1
done

# --- Wait for MCP backend via Caddy ---
echo "Waiting for MCP backend..."
for _ in $(seq 1 60); do
    curl -sf "${HTTP_BASE}/hackernews/ping" >/dev/null 2>&1 && break
    sleep 1
done

echo ""
echo "=== HTTP Tests ==="

check "Caddy health endpoint"          "${HTTP_BASE}/health"                    "200" "OK"
check "MCP health through Caddy"       "${HTTP_BASE}/hackernews/ping"           "200" "pong"
check "Service discovery"              "${HTTP_BASE}/.well-known/mcp.json"      "200" "hackernews"
check "Fallback redirect"              "${HTTP_BASE}/unknown"                   "302"

echo ""
echo "=== MCP Protocol over HTTP ==="
check_mcp "HTTP" "$HTTP_BASE"

echo ""
echo "=== HTTPS Tests ==="

# Wait for internal TLS cert generation
for _ in $(seq 1 30); do
    curl -sk "${HTTPS_BASE}/health" >/dev/null 2>&1 && break
    sleep 1
done

check "TLS health endpoint"            "${HTTPS_BASE}/health"                   "200" "OK"

echo ""
echo "=== MCP Protocol over HTTPS ==="
check_mcp "HTTPS" "$HTTPS_BASE"

echo ""
if [[ "$FAIL" -eq 0 ]]; then
    echo "All E2E tests passed."
else
    echo "Some E2E tests FAILED."
fi

exit $FAIL
