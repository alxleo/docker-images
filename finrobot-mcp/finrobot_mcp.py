"""Native FinRobot V2 MCP facade built from the pinned API's OpenAPI schema.

The adapter contains only transport policy: FastMCP generates the tools and
forwards calls to the API container. Financial computation stays in FinRobot.
"""

from __future__ import annotations

import os
import re

import httpx
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap
from finrobot.server import app as finrobot_app


ROUTE_NAMES: dict[tuple[str, str], str] = {
    ("POST", "/api/compute/wacc"): "compute_wacc",
    ("POST", "/api/compute/dcf"): "compute_dcf",
    ("POST", "/api/compute/dcf-seed"): "compute_dcf_seed",
    ("POST", "/api/compute/dcf-equivalence-line"): "compute_dcf_equivalence_line",
    ("POST", "/api/compute/dcf-sensitivity"): "compute_dcf_sensitivity",
    ("POST", "/api/compute/lbo"): "compute_lbo",
    ("POST", "/api/compute/lbo-seed"): "compute_lbo_seed",
    ("POST", "/api/compute/monte-carlo"): "compute_monte_carlo",
    ("POST", "/api/compute/sniper"): "compute_sniper",
    ("POST", "/api/runs"): "runs_create",
    ("GET", "/api/runs"): "runs_list",
    ("GET", "/api/runs/{run_id}"): "runs_get",
    ("GET", "/api/artifacts"): "artifacts_list",
    ("GET", "/api/artifacts/by-ticker/{ticker}/timeline"): "artifacts_timeline",
    ("GET", "/api/artifacts/{artifact_id}"): "artifacts_get",
    ("GET", "/api/artifacts/{a_id}/diff/{b_id}"): "artifacts_diff",
}


def route_maps() -> list[RouteMap]:
    """Return an exact allow-list followed by a fail-closed catch-all."""

    maps = [
        RouteMap(
            pattern=f"^{re.escape(path)}$",
            methods=[method],
            mcp_type=MCPType.TOOL,
        )
        for method, path in ROUTE_NAMES
    ]
    maps.append(RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE))
    return maps


def _name_component(route, component) -> None:
    key = (route.method.upper(), route.path)
    try:
        component.name = ROUTE_NAMES[key]
    except KeyError as error:
        raise RuntimeError(f"unlisted FinRobot route reached MCP adapter: {key}") from error


def build_mcp() -> FastMCP:
    api_url = os.environ.get("FINROBOT_API_URL", "http://127.0.0.1:8000").rstrip("/")
    # FinRobot's API intentionally rejects arbitrary Host headers. Keep the
    # service URL independently configurable while presenting its loopback
    # host allow-list value across a Docker network.
    backend_host = os.environ.get("FINROBOT_API_HOST_HEADER", "127.0.0.1")
    token = os.environ.get("FINROBOT_CAPABILITY_TOKEN")

    async def backend_headers(request: httpx.Request) -> None:
        # OpenAPI builds Host from the service URL before merging client
        # headers. Set the backend identity after that merge, and never
        # forward a caller's gateway credential to the private API.
        request.headers["Host"] = backend_host
        request.headers.pop("Authorization", None)
        if token:
            request.headers["Authorization"] = f"Bearer {token}"

    client = httpx.AsyncClient(
        base_url=api_url,
        timeout=60.0,
        trust_env=False,
        event_hooks={"request": [backend_headers]},
    )
    return FastMCP.from_openapi(
        openapi_spec=finrobot_app.openapi(),
        client=client,
        name="FinRobot V2 MCP",
        route_maps=route_maps(),
        mcp_component_fn=_name_component,
        strict_input_validation=True,
    )


if __name__ == "__main__":
    build_mcp().run(
        transport="streamable-http",
        host=os.environ.get("FINROBOT_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("FINROBOT_MCP_PORT", "8080")),
        show_banner=False,
    )
