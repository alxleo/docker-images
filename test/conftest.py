"""
Shared fixtures for MCP E2E stack tests.

Manages the Docker Compose stack lifecycle and provides HTTP helpers.
"""

import subprocess
import time

import pytest
import requests
import urllib3

# Suppress SSL warnings for self-signed certs in TLS tests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

COMPOSE_FILE = "docker-compose.mcp-e2e.yml"
HTTP_BASE = "http://localhost:8080"
HTTPS_BASE = "https://localhost:8443"
STARTUP_TIMEOUT = 120  # seconds


def _wait_for_url(url: str, timeout: int = 60, verify_ssl: bool = True) -> bool:
    """Poll a URL until it returns 200 or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=5, verify=verify_ssl)
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    """Start the Docker Compose E2E stack for the test session."""
    compose_dir = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip() + "/test"

    def compose(*args):
        return subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, *args],
            cwd=compose_dir,
            capture_output=True,
            text=True,
        )

    # Start stack
    result = compose("up", "-d", "--build", "--wait", "--wait-timeout", str(STARTUP_TIMEOUT))
    if result.returncode != 0:
        pytest.fail(f"docker compose up failed:\n{result.stderr}")

    # Wait for Caddy
    if not _wait_for_url(f"{HTTP_BASE}/health"):
        logs = compose("logs")
        pytest.fail(f"Caddy never became ready:\n{logs.stdout}\n{logs.stderr}")

    # Wait for backends through Caddy
    for service in ("hackernews", "arxiv"):
        if not _wait_for_url(f"{HTTP_BASE}/{service}/ping"):
            logs = compose("logs", service)
            pytest.fail(
                f"{service} backend never became ready:\n{logs.stdout}\n{logs.stderr}"
            )

    yield {
        "http_base": HTTP_BASE,
        "https_base": HTTPS_BASE,
        "compose_dir": compose_dir,
    }

    # Teardown
    compose("down", "-v")


def extract_json_from_sse(text: str) -> dict | None:
    """Extract JSON from an SSE or plain JSON response.

    mcp-proxy returns text/event-stream with 'data: {json}' lines.
    Falls back to parsing the entire response as plain JSON.
    """
    import json

    # Try SSE format: find first 'data: {...}' line
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                continue

    # Fall back to plain JSON
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def mcp_initialize(base_url: str, service_path: str) -> tuple[dict | None, str | None]:
    """Perform MCP initialize handshake.

    Returns (init_result, session_id) or (None, None) on failure.
    """
    resp = requests.post(
        f"{base_url}/{service_path}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pytest-e2e", "version": "1.0"},
            },
        },
        headers={
            "Accept": "application/json, text/event-stream",
        },
        timeout=10,
        verify=False,
    )
    result = extract_json_from_sse(resp.text)
    session_id = resp.headers.get("mcp-session-id")

    # Send initialized notification if we got a session
    if session_id:
        requests.post(
            f"{base_url}/{service_path}/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
            },
            timeout=10,
            verify=False,
        )

    return result, session_id


def mcp_tools_list(base_url: str, service_path: str, session_id: str) -> dict | None:
    """Call MCP tools/list and return the parsed result."""
    resp = requests.post(
        f"{base_url}/{service_path}/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
        },
        timeout=10,
        verify=False,
    )
    return extract_json_from_sse(resp.text)
