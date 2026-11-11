"""Search policy decisions, without imitating any transport or provider."""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent

spec = importlib.util.spec_from_file_location("search_server", Path(__file__).parents[1] / "server.py")
assert spec is not None and spec.loader is not None
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)


def test_search_content_about_quotas_is_success():
    result = CallToolResult(content=[TextContent(type="text", text="API quota exceeded troubleshooting guide")])
    assert server.result_failure(result) is None


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (402, "", "quota_exhausted"),
        (429, "", "rate_limited"),
        (None, "Your monthly quota has been exceeded", "quota_exhausted"),
        (None, "Insufficient credits", "quota_exhausted"),
        (None, "Rate limit exceeded", "rate_limited"),
    ],
)
def test_quota_and_rate_limits_select_a_backup(status, message, expected):
    assert server.quota_failure(status, message, is_error=True)[0] == expected


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500])
def test_other_failures_are_not_called_quota_exhaustion(status):
    assert server.quota_failure(status, "invalid request", is_error=True) is None


def test_native_mcp_quota_exception_selects_a_backup():
    assert server.exception_failure(MCPError(402, "Insufficient credits")) == ("quota_exhausted", 3600)
    assert server.exception_failure(MCPError(-32603, "Rate limit exceeded")) == ("rate_limited", 60)


def test_one_disconnected_account_does_not_disable_the_shared_pool():
    error = server.AccountReconnectRequired("Reconnect this shared account")
    assert server.exception_failure(error) == ("reconnect_required", 300)


def test_reload_keeps_cooldown_and_removes_revoked_accounts():
    accounts = server.accounts_from_json(json.dumps([account("one"), account("two", "test-two")]))
    pool = server.SearchPool(accounts)
    first = next(slot for slot in pool.slots if slot.name == "one")
    first.until = 12345
    pool.reload(server.accounts_from_json(json.dumps([account("one"), account("three", "test-three")])))
    retained = next(slot for slot in pool.slots if slot.name == "one")
    assert retained is first
    assert retained.until == 12345
    assert not any(slot.name == "two" for slot in pool.slots)
    assert any(slot.name == "three" for slot in pool.slots)


def test_structured_tool_error_is_classified_with_http_200():
    result = CallToolResult(content=[], structured_content={"success": False, "error": "Insufficient credits"})
    assert server.result_failure(result) == ("quota_exhausted", 3600)


def test_real_tavily_daily_cap_notice_even_without_mcp_error_flag():
    notice = {
        "code": "daily_cap_reached",
        "message": "You reached the daily keyless Tavily limit.",
        "retry_after_seconds": 1005,
        "window": "day",
    }
    structured = CallToolResult(content=[], structured_content=notice)
    text_only = CallToolResult(content=[TextContent(type="text", text=json.dumps(notice))])
    assert server.result_failure(structured) == ("quota_exhausted", 1005)
    assert server.result_failure(text_only) == ("quota_exhausted", 1005)


def test_retry_after_supports_seconds_and_http_dates():
    assert server.retry_seconds("90") == 90
    now = datetime(2026, 11, 11, 17, 0, tzinfo=UTC)
    assert server.retry_seconds("Wed, 11 Nov 2026 17:01:30 GMT", now=now) == 90
    assert server.retry_seconds("yesterday") is None


def account(name, key="test-one", **extra):
    return {"name": name, "provider": "exa", "api_key": key, "billing_mode": "free", **extra}


def test_same_key_does_not_manufacture_another_allowance():
    accounts = server.accounts_from_json(json.dumps([account("one"), account("alias"), account("two", "test-two")]))
    assert [a.name for a in accounts] == ["one", "two"]
    assert "test-one" not in repr(accounts)


def test_each_contributed_account_is_followed_by_the_anonymous_provider():
    accounts = server.accounts_from_json(json.dumps([account("one"), account("two", "test-two")]))
    assert [(s.provider, s.name) for s in server.make_slots(accounts)] == [
        ("parallel", "anonymous"),
        ("exa", "one"),
        ("exa", "two"),
        ("exa", "anonymous"),
        ("tavily", "anonymous"),
        ("firecrawl", "anonymous"),
    ]


def test_paid_or_unspecified_account_plans_are_rejected():
    for value in [account("paid", billing_mode="paygo"), {"name": "missing", "provider": "exa", "api_key": "test-key"}]:
        with pytest.raises(ValueError):
            server.accounts_from_json(json.dumps([value]))


def test_native_mcpjam_oauth_export_is_accepted_only_for_its_provider():
    oauth = {
        "accessToken": "test-access",
        "refreshToken": "test-refresh",
        "clientId": "test-client",
        "expiresAt": "2026-11-12T17:00:00Z",
        "serverUrl": "https://mcp.exa.ai/mcp?login",
    }
    value = {"name": "signed-in", "provider": "exa", "oauth": oauth, "billing_mode": "free"}
    assert server.accounts_from_json(json.dumps([value]))[0].oauth.clientId == "test-client"
    value["provider"] = "tavily"
    with pytest.raises(ValueError):
        server.accounts_from_json(json.dumps([value]))


def test_parallel_gets_its_actual_mcp_schema():
    assert server.arguments_for("parallel", "query", "objective", 1) == {
        "objective": "objective",
        "search_queries": ["query"],
    }
