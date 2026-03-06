"""
Shared fixtures for MCP E2E stack tests.

Manages the Docker Compose stack lifecycle and provides HTTP helpers.
"""

import json
import subprocess
import time
from pathlib import Path

import pytest
import requests
import urllib3

# Suppress SSL warnings for self-signed certs in TLS tests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

COMPOSE_FILE = "docker-compose.mcp-e2e.yml"
HTTP_BASE = "http://localhost:8080"
HTTPS_BASE = "https://localhost:8443"
STARTUP_TIMEOUT = 120  # seconds

# Load runtime defaults from manifest (source of truth)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_DEFAULTS = json.loads((_REPO_ROOT / "mcp-defaults.json").read_text())
HEALTH_PATH = _MCP_DEFAULTS["health_path"]


def _wait_for_url(url: str, timeout: int = 60, verify_ssl: bool = True) -> bool:
    """Poll a URL until it returns 200 or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=5, verify=verify_ssl)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def _wait_for_port(host: str, port: int, timeout: int = 30) -> bool:
    """Poll a TCP port until it accepts connections or timeout expires."""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
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
        if not _wait_for_url(f"{HTTP_BASE}/{service}{HEALTH_PATH}"):
            logs = compose("logs", f"mcp-{service}")
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


@pytest.fixture
def run_container():
    """Start a Docker container and clean up on teardown.

    Yields a factory function:
        info = start(image, name, env=None, ports=None, volumes=None,
                     cmd=None, health_url=None, timeout=30)

    info dict: {"name": str, "id": str}
    Cleanup (docker rm -f) runs regardless of test outcome.
    """
    containers = []

    def start(
        image: str,
        name: str,
        *,
        env: dict[str, str] | None = None,
        ports: dict[str, str] | None = None,
        volumes: list[str] | None = None,
        cmd: list[str] | None = None,
        health_url: str | None = None,
        health_port: int | None = None,
        timeout: int = 30,
    ) -> dict:
        docker_cmd = ["docker", "run", "-d", "--name", name]
        for k, v in (env or {}).items():
            docker_cmd.extend(["-e", f"{k}={v}"])
        for host_port, container_port in (ports or {}).items():
            docker_cmd.extend(["-p", f"{host_port}:{container_port}"])
        for vol in volumes or []:
            docker_cmd.extend(["-v", vol])
        docker_cmd.append(image)
        if cmd:
            docker_cmd.extend(cmd)

        result = subprocess.run(docker_cmd, capture_output=True, text=True)
        assert result.returncode == 0, (
            f"docker run failed: {result.stderr}"
        )
        container_id = result.stdout.strip()
        containers.append(name)

        if health_url:
            assert _wait_for_url(health_url, timeout=timeout), (
                f"Container {name} never became healthy at {health_url}"
            )
        elif health_port:
            assert _wait_for_port("localhost", health_port, timeout=timeout), (
                f"Container {name} port {health_port} never became ready"
            )

        return {"name": name, "id": container_id}

    yield start

    for name in containers:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
        )


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
