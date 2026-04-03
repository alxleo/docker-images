"""
Tool filtering integration tests — FILTER_INCLUDE/EXCLUDE with live containers.

Uses the hackernews MCP canary to validate that mcp-filter correctly
includes/excludes tools from tools/list responses. Also tests Docker
secret injection into environment variables.

Requires Docker. CI runs these in the mcp-smoke-test job.
"""

import os
import subprocess

import pytest
import requests
from conftest import extract_json_from_sse

MCP_IMAGE = os.environ.get("TEST_MCP_IMAGE", "test-mcp-hackernews:latest")
BASE_PORT = 18090


def _build_hackernews_image():
    """Build the hackernews canary image if not already available."""
    result = subprocess.run(
        ["docker", "image", "inspect", MCP_IMAGE],
        capture_output=True,
    )
    if result.returncode == 0:
        return  # Already built

    repo_root = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
    result = subprocess.run(
        [
            "docker", "build",
            "-f", f"{repo_root}/mcp/Dockerfile.npm",
            "--build-arg", "MCP_PACKAGE=mcp-hacker-news@1.0.3",
            "-t", MCP_IMAGE,
            f"{repo_root}/mcp",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Build failed: {result.stderr}"


def _mcp_tools_list(port: int) -> list[str]:
    """Perform MCP initialize + tools/list and return tool names."""
    base = f"http://localhost:{port}"

    # Initialize
    resp = requests.post(
        f"{base}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "filter-test", "version": "1.0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
        timeout=10,
    )
    init_result = extract_json_from_sse(resp.text)
    assert init_result is not None, "Initialize failed"
    assert "error" not in init_result, f"Initialize error: {init_result['error']}"
    session_id = resp.headers.get("mcp-session-id")

    # Send initialized notification
    headers = {"Accept": "application/json, text/event-stream"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    requests.post(
        f"{base}/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
        timeout=10,
    )

    # tools/list
    resp = requests.post(
        f"{base}/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
        timeout=10,
    )
    result = extract_json_from_sse(resp.text)
    assert result is not None, "tools/list failed"
    assert "error" not in result, f"tools/list returned error: {result['error']}"
    tools = result.get("result", {}).get("tools", [])
    return [t["name"] for t in tools]


@pytest.fixture(scope="module", autouse=True)
def _ensure_image():
    """Build the MCP canary image once per test module."""
    _build_hackernews_image()


# =========================================================================
# Tool filtering
# =========================================================================


class TestToolFiltering:
    """Validate FILTER_INCLUDE/EXCLUDE with a live MCP container."""

    def test_no_filter_baseline(self, run_container):
        """Without filtering, tools/list returns all tools."""
        port = BASE_PORT
        run_container(
            MCP_IMAGE,
            "test-filter-baseline",
            env={"MCP_STARTUP_JITTER": "0"},
            ports={str(port): "8080"},
            health_url=f"http://localhost:{port}/ping",
            timeout=30,
        )
        tools = _mcp_tools_list(port)
        assert len(tools) > 0, "Baseline should have at least one tool"

    def test_filter_exclude(self, run_container):
        """FILTER_EXCLUDE removes specific tools from tools/list."""
        port = BASE_PORT + 1
        # First get baseline to know a tool name
        run_container(
            MCP_IMAGE,
            "test-filter-exclude-baseline",
            env={"MCP_STARTUP_JITTER": "0"},
            ports={str(port): "8080"},
            health_url=f"http://localhost:{port}/ping",
            timeout=30,
        )
        baseline_tools = _mcp_tools_list(port)
        assert len(baseline_tools) > 0
        excluded_tool = baseline_tools[0]

        # Now run with FILTER_EXCLUDE
        port2 = BASE_PORT + 2
        run_container(
            MCP_IMAGE,
            "test-filter-exclude",
            env={
                "MCP_STARTUP_JITTER": "0",
                "FILTER_EXCLUDE": excluded_tool,
            },
            ports={str(port2): "8080"},
            health_url=f"http://localhost:{port2}/ping",
            timeout=30,
        )
        filtered_tools = _mcp_tools_list(port2)
        assert excluded_tool not in filtered_tools, (
            f"Tool '{excluded_tool}' should have been excluded"
        )

    def test_filter_include(self, run_container):
        """FILTER_INCLUDE keeps only specified tools in tools/list."""
        port = BASE_PORT + 3
        # Get baseline
        run_container(
            MCP_IMAGE,
            "test-filter-include-baseline",
            env={"MCP_STARTUP_JITTER": "0"},
            ports={str(port): "8080"},
            health_url=f"http://localhost:{port}/ping",
            timeout=30,
        )
        baseline_tools = _mcp_tools_list(port)
        assert len(baseline_tools) > 1, "Need at least 2 tools to test include"
        included_tool = baseline_tools[0]

        # Run with FILTER_INCLUDE
        port2 = BASE_PORT + 4
        run_container(
            MCP_IMAGE,
            "test-filter-include",
            env={
                "MCP_STARTUP_JITTER": "0",
                "FILTER_INCLUDE": included_tool,
            },
            ports={str(port2): "8080"},
            health_url=f"http://localhost:{port2}/ping",
            timeout=30,
        )
        filtered_tools = _mcp_tools_list(port2)
        assert filtered_tools == [included_tool], (
            f"Expected only [{included_tool}], got {filtered_tools}"
        )


# =========================================================================
# Docker secret injection
# =========================================================================


class TestSecretInjection:
    """Validate entrypoint.py injects /run/secrets/* into environment.

    `docker exec env` spawns a new process with Docker's original env,
    NOT PID 1's modified env. The entrypoint sets vars via os.environ
    then execvp, so only PID 1 has them. We read /proc/1/environ instead.
    """

    @staticmethod
    def _pid1_env(container_name: str) -> str:
        """Read PID 1's environment from /proc/1/environ (null-separated)."""
        result = subprocess.run(
            [
                "docker", "exec", container_name,
                "sh", "-c", "tr '\\0' '\\n' < /proc/1/environ",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Failed to read PID 1 env: {result.stderr}"
        return result.stdout

    def test_docker_secret_env_injection(self, run_container, tmp_path):
        """Secret file content becomes an environment variable in PID 1."""
        secret_file = tmp_path / "brave_api_key"
        secret_file.write_text("test-secret-value")

        port = BASE_PORT + 5
        run_container(
            MCP_IMAGE,
            "test-secret-inject",
            env={"MCP_STARTUP_JITTER": "0"},
            ports={str(port): "8080"},
            volumes=[f"{secret_file}:/run/secrets/brave_api_key:ro"],
            health_url=f"http://localhost:{port}/ping",
            timeout=30,
        )
        env_output = self._pid1_env("test-secret-inject")
        assert "BRAVE_API_KEY=test-secret-value" in env_output

    def test_docker_secret_uppercase(self, run_container, tmp_path):
        """Secret filenames are uppercased in PID 1's environment."""
        secret_file = tmp_path / "my_token"
        secret_file.write_text("token-123")

        port = BASE_PORT + 6
        run_container(
            MCP_IMAGE,
            "test-secret-upper",
            env={"MCP_STARTUP_JITTER": "0"},
            ports={str(port): "8080"},
            volumes=[f"{secret_file}:/run/secrets/my_token:ro"],
            health_url=f"http://localhost:{port}/ping",
            timeout=30,
        )
        env_output = self._pid1_env("test-secret-upper")
        assert "MY_TOKEN=token-123" in env_output
