#!/usr/bin/env bash
set -euo pipefail

image="${FINROBOT_TEST_IMAGE:?FINROBOT_TEST_IMAGE is required}"
network="finrobot-image-test"
api="finrobot-api-image-test"
mcp="finrobot-mcp-image-test"
api_port=18083
mcp_port=18082
token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
cleanup() {
    docker rm -f "$mcp" "$api" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$api" --network "$network" -p "${api_port}:8000" \
    -e FINROBOT_CAPABILITY_TOKEN="$token" "$image" api >/dev/null
ready=false
for _ in $(seq 1 90); do
    health="$(curl -fsS "http://127.0.0.1:${api_port}/health" 2>/dev/null || true)"
    if HEALTH_JSON="$health" python3 -c 'import json,os; v=json.loads(os.environ["HEALTH_JSON"]); raise SystemExit(0 if v.get("engine_ready") is True and v.get("agents_ready") is True else 1)' 2>/dev/null; then
        ready=true
        break
    fi
    sleep 1
done
test "$ready" = true
docker run -d --name "$mcp" --network "$network" -p "${mcp_port}:8080" \
    -e FINROBOT_API_URL="http://${api}:8000" \
    -e FINROBOT_CAPABILITY_TOKEN="$token" \
    -e FINROBOT_API_HOST_HEADER=127.0.0.1 "$image" mcp >/dev/null
ready=false
for _ in $(seq 1 90); do
    if docker exec -e FINROBOT_MODE=mcp "$mcp" /usr/local/bin/python /app/healthcheck.py >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
test "$ready" = true

TEST_URL="http://127.0.0.1:${mcp_port}/mcp" python3 - <<'PY'
import importlib.util
import os

spec = importlib.util.spec_from_file_location("mcp_contract", "scripts/mcp-contract.py")
assert spec and spec.loader
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
client = contract.MCPClient(os.environ["TEST_URL"])
client.initialize()
names = {tool["name"] for tool in client.list_tools()}
expected = {"compute_wacc", "compute_dcf", "runs_create", "runs_get", "artifacts_list", "artifacts_get"}
assert expected <= names
assert "artifacts_delete" not in names
assert "artifacts_view" not in names
assert "runs_cancel" not in names
assert "chat" not in names
result = client._request("tools/call", {
    "name": "compute_wacc",
    "arguments": {"risk_free_rate": 0.03, "beta": 1.1, "equity_risk_premium": 0.05,
                  "cost_of_debt": 0.04, "tax_rate": 0.21, "debt_ratio": 0.2},
})
assert not result.get("isError"), result
import json
computed = result.get("structuredContent")
if not computed:
    computed = json.loads(result["content"][0]["text"])
assert abs(computed["wacc"] - 0.07432) < 1e-8, computed
print(f"FinRobot MCP tools: {len(names)}; destructive routes absent")
PY

wacc="$(curl -fsS -H 'Content-Type: application/json' -H "Authorization: Bearer $token" \
    -d '{"risk_free_rate":0.03,"beta":1.1,"equity_risk_premium":0.05,"cost_of_debt":0.04,"tax_rate":0.21,"debt_ratio":0.2}' \
    "http://127.0.0.1:${api_port}/api/compute/wacc")"
WACC_JSON="$wacc" python3 - <<'PY'
import json
import os
value = json.loads(os.environ["WACC_JSON"])
assert abs(value["wacc"] - 0.07432) < 1e-8, value
print("WACC deterministic call passed")
PY

dcf="$(curl -fsS -H 'Content-Type: application/json' -H "Authorization: Bearer $token" \
    -d '{"revenue_base":100,"revenue_growth_rates":[0.05,0.04,0.03],"ebitda_margin":0.2,"capex_pct_revenue":0.05,"nwc_pct_revenue":0.01,"da_pct_revenue":0.05,"tax_rate":0.21,"risk_free_rate":0.04,"beta":1.0,"equity_risk_premium":0.05,"cost_of_debt":0.04,"debt_ratio":0.2,"terminal_growth_rate":0.02,"shares_outstanding":10,"net_debt":20}' \
    "http://127.0.0.1:${api_port}/api/compute/dcf")"
DCF_JSON="$dcf" python3 - <<'PY'
import json
import os
value = json.loads(os.environ["DCF_JSON"])
assert value["projection_years"] == 3
assert value["implied_price"] > 0
print("DCF deterministic call passed")
PY
