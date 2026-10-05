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

TEST_URL="http://127.0.0.1:${port}/mcp" python3 - <<'PY'
import importlib.util
import os

spec = importlib.util.spec_from_file_location("mcp_contract", "scripts/mcp-contract.py")
assert spec and spec.loader
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
client = contract.MCPClient(os.environ["TEST_URL"])
client.initialize()
tools = {tool["name"] for tool in client.list_tools()}
assert "install_skill" not in tools
assert "run_pipeline" not in tools
for name in ("install_skill", "run_pipeline"):
    try:
        result = client._request("tools/call", {"name": name, "arguments": {}})
        assert result.get("isError") is True, result
        message = str(result).lower()
    except contract.ContractError as error:
        message = str(error).lower()
    assert any(term in message for term in ("unknown tool", "not found", "disabled")), message
assert any(name.startswith("ecb_") for name in tools)
assert any(name.startswith("fred_") for name in tools)
assert any(name.startswith("imf_") for name in tools)
assert any(name.startswith("sec_") for name in tools)
assert not any(name.startswith(("openbb_dispatch", "openbb_batch_dispatch", "openbb_config", "coverage_")) for name in tools)
print(f"OpenBB MCP tools: {len(tools)}; mutating and CLI helpers absent")
PY
