"""
Functional tests for custom-built Docker images.

Each image gets validation beyond build + Trivy scan. Tests use pytest
marks so CI jobs run only the relevant subset (e.g., pytest -m cadvisor).

Image tags are passed via environment variables (TEST_IMAGE_TAG) set
in CI workflow steps after the build-push-action loads the image.
"""

import json
import os
import subprocess

import pytest
import requests

from conftest import _wait_for_url, extract_json_from_sse


def _get_image_tag(env_var: str, default: str) -> str:
    """Get image tag from env var or fall back to default."""
    return os.environ.get(env_var, default)


# =========================================================================
# caddy-cloudflare
# =========================================================================


@pytest.mark.caddy_cloudflare
class TestCaddyCloudflare:
    """Validate Caddy + Cloudflare DNS plugin is correctly built."""

    IMAGE = _get_image_tag(
        "TEST_CADDY_CLOUDFLARE_TAG", "ghcr.io/alxleo/caddy-cloudflare:2.11"
    )

    def test_cloudflare_module_loaded(self):
        """The Cloudflare DNS provider module must be compiled in."""
        result = subprocess.run(
            ["docker", "run", "--rm", self.IMAGE, "caddy", "list-modules"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"caddy list-modules failed: {result.stderr}"
        assert "dns.providers.cloudflare" in result.stdout

    def test_caddy_version(self):
        """Caddy binary reports expected version."""
        result = subprocess.run(
            ["docker", "run", "--rm", self.IMAGE, "caddy", "version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip().startswith("v2.")


# =========================================================================
# cadvisor
# =========================================================================


@pytest.mark.cadvisor
class TestCadvisor:
    """Validate cAdvisor starts and serves metrics API."""

    IMAGE = _get_image_tag(
        "TEST_CADVISOR_TAG", "ghcr.io/alxleo/cadvisor:v0.56.2"
    )

    def test_cadvisor_starts(self, run_container):
        """cAdvisor container starts and becomes healthy."""
        run_container(
            self.IMAGE,
            "test-cadvisor",
            ports={"18080": "8080"},
            volumes=["/var/run/docker.sock:/var/run/docker.sock:ro"],
            health_url="http://localhost:18080/healthz",
            timeout=30,
        )

    def test_cadvisor_machine_api(self, run_container):
        """cAdvisor /api/v1.3/machine returns machine info."""
        run_container(
            self.IMAGE,
            "test-cadvisor-api",
            ports={"18081": "8080"},
            volumes=["/var/run/docker.sock:/var/run/docker.sock:ro"],
            health_url="http://localhost:18081/healthz",
            timeout=30,
        )
        r = requests.get("http://localhost:18081/api/v1.3/machine", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "num_cores" in data


# =========================================================================
# git-mcp-server
# =========================================================================


@pytest.mark.git_mcp_server
class TestGitMCPServer:
    """Validate git-mcp-server starts and speaks MCP protocol."""

    IMAGE = _get_image_tag(
        "TEST_GIT_MCP_TAG", "ghcr.io/alxleo/mcp-git:2.8.4"
    )

    def test_git_mcp_starts(self, run_container):
        """git-mcp-server starts with GIT_BASE_DIR and accepts HTTP."""
        # git-mcp-server uses native HTTP transport (no mcp-proxy), so no /ping.
        # Poll /mcp with GET — any response (even 405) means HTTP is ready.
        run_container(
            self.IMAGE,
            "test-git-mcp",
            env={"GIT_BASE_DIR": "/data"},
            ports={"18082": "8080"},
            health_url="http://localhost:18082/mcp",
            health_any_response=True,
            timeout=30,
        )

    def test_git_mcp_initialize(self, run_container):
        """MCP initialize handshake returns capabilities."""
        run_container(
            self.IMAGE,
            "test-git-mcp-init",
            env={"GIT_BASE_DIR": "/data"},
            ports={"18083": "8080"},
            health_url="http://localhost:18083/mcp",
            health_any_response=True,
            timeout=30,
        )
        resp = requests.post(
            "http://localhost:18083/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest-custom", "version": "1.0"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
            timeout=10,
        )
        result = extract_json_from_sse(resp.text)
        assert result is not None, "No valid JSON response"
        assert "capabilities" in result.get("result", {}), (
            f"No capabilities in response: {result}"
        )


# =========================================================================
# mcp-auth-proxy
# =========================================================================


@pytest.mark.mcp_auth_proxy
class TestMCPAuthProxy:
    """Validate mcp-auth-proxy has the VARCHAR fix applied."""

    IMAGE = _get_image_tag(
        "TEST_MCP_AUTH_PROXY_TAG", "ghcr.io/alxleo/mcp-auth-proxy:v2.5.3"
    )

    def test_varchar_patch_applied(self):
        """The size:512 patch is present in the compiled binary.

        The sed command in the Dockerfile replaces 7 'size:255' → 'size:512'
        in pkg/repository/sql.go. Go embeds struct tags as string literals,
        so grep -ac finds them in the binary. No `strings` (binutils) needed.
        """
        result = subprocess.run(
            [
                "docker", "run", "--rm", "--entrypoint", "sh",
                self.IMAGE, "-c",
                "grep -ac 'size:512' /usr/local/bin/mcp-auth-proxy",
            ],
            capture_output=True,
            text=True,
        )
        # grep -ac counts lines with matches in binary mode
        assert result.returncode == 0, f"grep failed: {result.stderr}"
        count = int(result.stdout.strip())
        assert count >= 1, (
            f"Expected 'size:512' in binary (VARCHAR fix), got {count} matches"
        )


# =========================================================================
# Image metadata
# =========================================================================


@pytest.mark.mcp_metadata
class TestMCPImageMetadata:
    """Validate MCP image metadata (EXPOSE, labels)."""

    def test_mcp_image_exposes_8080(self):
        """MCP canary image exposes port 8080."""
        result = subprocess.run(
            [
                "docker", "inspect",
                "--format", "{{json .Config.ExposedPorts}}",
                "ghcr.io/alxleo/mcp-hackernews:latest",
            ],
            capture_output=True,
            text=True,
        )
        # Image may not be available locally; skip if inspect fails
        if result.returncode != 0:
            pytest.skip("MCP canary image not available locally")
        ports = json.loads(result.stdout)
        assert "8080/tcp" in ports, f"Port 8080 not exposed: {ports}"
