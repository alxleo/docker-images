"""
MCP E2E stack tests — contract validation for downstream consumers.

Tests the full Caddy → mcp-proxy → MCP server chain with both
npm (hackernews) and Python (arxiv) canaries.

This is the contract test that downstream repos (homelab) depend on:
- Health endpoint: GET /ping → 200 "pong"
- MCP protocol: initialize → capabilities, tools/list → tools
- Caddy routing: prefix stripping, health_uri, SSE passthrough
- TLS: internal certs, HTTPS passthrough
- Service discovery: .well-known/mcp.json
"""

import warnings

import pytest
import requests

from conftest import extract_json_from_sse, mcp_initialize, mcp_tools_list

# Both canary types: npm and Python Dockerfiles
MCP_SERVICES = ["hackernews", "arxiv"]

# Caddy admin API (health probe status)
CADDY_ADMIN = "http://localhost:2019"

# Map from Caddy upstream address to service name for readable assertions
EXPECTED_UPSTREAMS = {
    "mcp-hackernews:8080": "hackernews",
    "mcp-arxiv:8080": "arxiv",
}


# =========================================================================
# Health endpoint contract
# =========================================================================


class TestHealthContract:
    """Health endpoint contract — the guarantee downstream repos rely on.

    Every MCP container serves GET /ping → 200 "pong" via mcp-proxy.
    Caddy uses this as health_uri for backend health checking.
    """

    def test_caddy_self_health(self, stack):
        r = requests.get(f"{stack['http_base']}/health", timeout=5)
        assert r.status_code == 200
        assert r.text == "OK"

    @pytest.mark.parametrize("service", MCP_SERVICES)
    def test_ping_through_caddy(self, stack, service):
        """GET /ping returns 200 'pong' through Caddy prefix stripping."""
        r = requests.get(f"{stack['http_base']}/{service}/ping", timeout=5)
        assert r.status_code == 200
        assert r.text == "pong"

    @pytest.mark.parametrize("service", MCP_SERVICES)
    def test_ping_through_caddy_tls(self, stack, service):
        """Same contract holds over TLS."""
        r = requests.get(
            f"{stack['https_base']}/{service}/ping", timeout=5, verify=False
        )
        assert r.status_code == 200
        assert r.text == "pong"


# =========================================================================
# Caddy health probes — validates health_uri config works with MCP images
# =========================================================================


class TestCaddyHealthProbe:
    """Verify Caddy's active health probes see MCP backends as healthy.

    This is the test that matters for downstream: Caddy's health_uri /ping
    must work with MCP containers. If mcp-proxy changes /ping, Caddy marks
    backends unhealthy and all traffic returns 502.

    Queries Caddy's admin API (/reverse_proxy/upstreams) for actual probe
    results — not just that the endpoint responds, but that Caddy itself
    considers the backend healthy.
    """

    def test_all_upstreams_registered(self, stack):
        """Caddy knows about all expected MCP backends."""
        r = requests.get(f"{CADDY_ADMIN}/reverse_proxy/upstreams", timeout=5)
        assert r.status_code == 200
        upstreams = r.json()
        addresses = {u["address"] for u in upstreams}
        for addr in EXPECTED_UPSTREAMS:
            assert addr in addresses, (
                f"Missing upstream {addr} ({EXPECTED_UPSTREAMS[addr]}). "
                f"Registered: {addresses}"
            )

    def test_no_unhealthy_upstreams(self, stack):
        """All MCP backends pass Caddy's health_uri /ping probe.

        Caddy tracks num_requests and fails per upstream. A backend with
        fails > 0 means health_uri returned non-2xx — the health contract
        is broken. This catches mcp-proxy changing/removing /ping before
        downstream deploys break.
        """
        r = requests.get(f"{CADDY_ADMIN}/reverse_proxy/upstreams", timeout=5)
        upstreams = r.json()
        for upstream in upstreams:
            addr = upstream["address"]
            if addr not in EXPECTED_UPSTREAMS:
                continue
            service = EXPECTED_UPSTREAMS[addr]
            assert upstream.get("num_requests", 0) >= 0, (
                f"{service} ({addr}): unexpected negative request count"
            )
            # A non-zero fails count means health_uri probe failed
            assert upstream.get("fails", 0) == 0, (
                f"{service} ({addr}): Caddy health probe failed "
                f"(fails={upstream['fails']}). "
                f"health_uri /ping may not be working."
            )


# =========================================================================
# MCP protocol
# =========================================================================


class TestMCPProtocol:
    """MCP protocol handshake through the full Caddy → mcp-proxy chain.

    Validates initialize (capabilities), session headers, and tools/list
    for both npm and Python canaries over HTTP and HTTPS.
    """

    @pytest.mark.parametrize("service", MCP_SERVICES)
    def test_initialize_http(self, stack, service):
        result, session_id = mcp_initialize(stack["http_base"], service)
        assert result is not None, f"{service}: no valid JSON response"
        assert "result" in result, f"{service}: no result key: {result}"
        assert "capabilities" in result["result"], f"{service}: no capabilities"

    @pytest.mark.parametrize("service", MCP_SERVICES)
    def test_session_header(self, stack, service):
        _, session_id = mcp_initialize(stack["http_base"], service)
        if session_id is None:
            warnings.warn(f"{service}: no Mcp-Session-Id header (stateless mode)")
            pytest.skip("Server running in stateless mode")
        assert len(session_id) > 0

    @pytest.mark.parametrize("service", MCP_SERVICES)
    def test_tools_list_http(self, stack, service):
        _, session_id = mcp_initialize(stack["http_base"], service)
        if session_id is None:
            pytest.skip("No session ID")

        result = mcp_tools_list(stack["http_base"], service, session_id)
        assert result is not None, f"{service}: no tools/list response"
        tools = result.get("result", {}).get("tools", [])
        assert len(tools) > 0, f"{service}: tools/list returned no tools"

    @pytest.mark.parametrize("service", MCP_SERVICES)
    def test_initialize_https(self, stack, service):
        result, _ = mcp_initialize(stack["https_base"], service)
        assert result is not None, f"{service} HTTPS: no valid JSON response"
        assert "capabilities" in result.get("result", {})

    @pytest.mark.parametrize("service", MCP_SERVICES)
    def test_tools_list_https(self, stack, service):
        _, session_id = mcp_initialize(stack["https_base"], service)
        if session_id is None:
            pytest.skip("No session ID")

        result = mcp_tools_list(stack["https_base"], service, session_id)
        assert result is not None
        tools = result.get("result", {}).get("tools", [])
        assert len(tools) > 0


# =========================================================================
# Routing
# =========================================================================


class TestRouting:
    """Caddy routing patterns: service discovery, prefix stripping, fallback."""

    def test_service_discovery(self, stack):
        r = requests.get(
            f"{stack['http_base']}/.well-known/mcp.json", timeout=5
        )
        assert r.status_code == 200
        data = r.json()
        assert "hackernews" in data["services"]
        assert "arxiv" in data["services"]

    def test_fallback_redirect(self, stack):
        r = requests.get(
            f"{stack['http_base']}/unknown", timeout=5, allow_redirects=False
        )
        assert r.status_code == 302

    def test_tls_caddy_health(self, stack):
        r = requests.get(f"{stack['https_base']}/health", timeout=5, verify=False)
        assert r.status_code == 200
        assert r.text == "OK"
