#!/usr/bin/env bash
# Caddy routing E2E tests — validates patterns used in production
#
# Exercises: snippet import, handle_path prefix stripping, handle {} mutual
# exclusivity, health endpoint coexistence, redir fallback.
#
# This would have caught the redir-shadows-handle_path directive ordering bug
# (Caddy redir pos 10 > handle_path pos 27) before deploy.
set -euo pipefail

BASE="http://localhost:8080"
FAIL=0

check() {
    local desc="$1" url="$2" expect_code="$3" expect_body="${4:-}"
    local code body
    code=$(curl -s -o /tmp/test-body -w '%{http_code}' --max-time 5 "$url")
    body=$(cat /tmp/test-body)
    if [[ "$code" != "$expect_code" ]]; then
        echo "FAIL: $desc — expected $expect_code, got $code"
        FAIL=1
    elif [[ -n "$expect_body" && "$body" != *"$expect_body"* ]]; then
        echo "FAIL: $desc — body missing '$expect_body'"
        FAIL=1
    else
        echo "PASS: $desc"
    fi
}

echo "Waiting for Caddy..."
for _ in $(seq 1 30); do
    curl -sf "$BASE/health" >/dev/null 2>&1 && break
    sleep 1
done

check "Routes work on HTTP"           "$BASE/echo/test"   "200"  "pong"
check "Health endpoint not shadowed"   "$BASE/health"      "200"  "OK"
check "Prefix stripping works"         "$BASE/echo/test"   "200"  "pong"
check "Fallback redirect (no follow)"  "$BASE/unknown"     "301"
check "Route not caught by redirect"   "$BASE/echo/mcp"    "200"  "pong"

if [[ "$FAIL" -eq 0 ]]; then
    echo ""
    echo "All tests passed."
else
    echo ""
    echo "Some tests FAILED."
fi

exit $FAIL
