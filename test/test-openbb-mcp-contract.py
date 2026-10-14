"""Exercise the OpenBB MCP inventory and single-symbol statement contract."""

import importlib.util
import os
from pathlib import Path

contract_path = Path(__file__).resolve().parents[1] / "scripts/mcp-contract.py"
spec = importlib.util.spec_from_file_location("mcp_contract", contract_path)
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
assert any(name.startswith("bls_") for name in tools)
assert any(name.startswith("cboe_") for name in tools)
assert any(name.startswith("nasdaq_") for name in tools)
assert any(name.startswith("federal_reserve_") for name in tools)
assert any(name.startswith("yfinance_") for name in tools)
assert not any(
    name.startswith(("openbb_dispatch", "openbb_batch_dispatch", "openbb_config", "coverage_")) for name in tools
)
for name in (
    "yfinance_equity_fundamental_income",
    "yfinance_equity_fundamental_balance",
    "yfinance_equity_fundamental_cash",
):
    result = client._request("tools/call", {"name": name, "arguments": {"symbol": "MSFT,ULVR.L"}})
    assert result.get("isError") is True, result
    detail = " ".join(block.get("text", "") for block in result.get("content", []))
    assert "422" in detail and "one symbol per request" in detail, detail

print(f"OpenBB MCP tools: {len(tools)}; mutating and CLI helpers absent")
