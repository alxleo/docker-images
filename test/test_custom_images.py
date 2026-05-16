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
from conftest import extract_json_from_sse

REGISTRY = "ghcr.io/alxleo"

# Load custom image tags from manifest (single source of truth)
_manifest_path = os.path.join(os.path.dirname(__file__), "..", "custom-images.json")
with open(_manifest_path) as _f:
    _CUSTOM_TAGS = {img["name"]: img["tag"] for img in json.load(_f)}


def _get_image_tag(env_var: str, image_name: str) -> str:
    """Get image tag from env var or fall back to custom-images.json."""
    return os.environ.get(env_var, f"{REGISTRY}/{image_name}:{_CUSTOM_TAGS[image_name]}")


# =========================================================================
# caddy-cloudflare
# =========================================================================


@pytest.mark.caddy_cloudflare
class TestCaddyCloudflare:
    """Validate Caddy + Cloudflare DNS plugin is correctly built."""

    IMAGE = _get_image_tag("TEST_CADDY_CLOUDFLARE_TAG", "caddy-cloudflare")

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

    IMAGE = _get_image_tag("TEST_CADVISOR_TAG", "cadvisor")

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

    IMAGE = _get_image_tag("TEST_GIT_MCP_TAG", "mcp-git")

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
    """Validate mcp-auth-proxy has size:512 on all session-storage fields.

    Originally guarded a local Dockerfile sed patch for sigbit/mcp-auth-proxy#111.
    Upstream merged the fix in v2.9.x; we still build from source on our base-images,
    so the binary should still contain size:512. Test stays as a regression check —
    fails if upstream ever shrinks the field width back to 255.
    """

    IMAGE = _get_image_tag("TEST_MCP_AUTH_PROXY_TAG", "mcp-auth-proxy")

    def test_size_512_session_fields(self):
        """The size:512 GORM tag is present in the compiled binary, with no size:255 regressions.

        Upstream v2.9.1+ ships pkg/repository/sql.go with seven `size:512` GORM tags
        across the AuthorizationCode, AccessToken, RefreshToken, Session and DCRClient
        structs. Go's compiler interns identical tag-string literals, so the binary
        typically contains fewer distinct copies than there are fields (3 observed
        for v2.9.1). The exact count is not load-bearing here — only that:

          - at least one `size:512` literal is present (sanity check; would be 0 if
            upstream nuked the whole feature), AND
          - zero `size:255` literals are present (catches partial regressions — if
            even one field shrinks back to 255, that string would appear).

        Uses docker cp to extract the binary since the runtime image is minimal.
        """
        import tempfile

        # Use container ID (not name) to avoid conflicts with concurrent runs
        create = subprocess.run(
            ["docker", "create", self.IMAGE],
            capture_output=True, text=True, check=True,
        )
        container_id = create.stdout.strip()
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix="-mcp-auth-proxy") as tmp:
                tmp_path = tmp.name
            subprocess.run(
                ["docker", "cp", f"{container_id}:/usr/local/bin/mcp-auth-proxy", tmp_path],
                capture_output=True, text=True, check=True,
            )
            # grep -c return codes: 0 = found (count in stdout), 1 = no matches
            # (count=0), 2 = grep itself errored (unreadable file, etc).
            def _grep_count(pattern: str) -> int:
                r = subprocess.run(
                    ["grep", "-ac", pattern, tmp_path],
                    capture_output=True, text=True,
                )
                assert r.returncode in (0, 1), (
                    f"grep -ac {pattern!r} errored (rc={r.returncode}): {r.stderr}"
                )
                return int(r.stdout.strip()) if r.stdout.strip() else 0

            count_512 = _grep_count("size:512")
            assert count_512 >= 1, (
                "No 'size:512' tags found in binary — upstream may have removed "
                "the wider field width entirely"
            )

            count_255 = _grep_count("size:255")
            assert count_255 == 0, (
                f"Found {count_255} 'size:255' tags in binary — upstream sql.go "
                f"may have regressed one or more session-storage fields back to 255"
            )
        finally:
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass

    def test_alpine_runtime_provides_shell_curl_root_data(self):
        """The Alpine runtime layer provides shell + curl + root + writable /data.

        Operators using a /bin/sh -c entrypoint wrapper (to materialize env from
        Docker secret files at startup) depend on several runtime-surface
        guarantees. This test exercises each so a future runtime-base change
        that breaks any one of them fails loudly:

          - /bin/sh exists and runs
          - ca-certificates bundle is readable (TLS to OAuth IDPs)
          - curl is installed (typical healthcheck dep)
          - container runs as root (Compose short-syntax mounts secrets at
            mode 0640 host-uid-owned; non-root UIDs inside the container can't
            read them — PR #153 hit this regression)
          - /data is writable
          - root can read a 0640 file with uid 0 / gid 1000 (production-parity
            for the secret mount mode)
        """
        # NOTE: every `docker run` here uses --entrypoint to OVERRIDE the image's
        # ENTRYPOINT (which is /usr/local/bin/mcp-auth-proxy). Without the override,
        # the trailing args are appended as flags to the binary, not run by /bin/sh —
        # which means a missing shell wouldn't fail this test, silently inverting
        # its purpose.

        # /bin/sh runs and can exec a builtin
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/sh", self.IMAGE, "-c", "echo shell-ok"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"/bin/sh missing or broken: rc={r.returncode}, stderr={r.stderr}"
        assert "shell-ok" in r.stdout, f"shell did not echo as expected: {r.stdout!r}"

        # CA cert bundle present and non-empty (OAuth IDPs need it)
        ca_cmd = "wc -c </etc/ssl/certs/ca-certificates.crt"
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/sh", self.IMAGE, "-c", ca_cmd],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"ca-certificates bundle unreadable: {r.stderr}"
        ca_bytes = int(r.stdout.strip())
        assert ca_bytes > 100_000, f"ca-certificates bundle suspiciously small ({ca_bytes} bytes)"

        # curl exists (homelab healthcheck depends on it)
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/sh", self.IMAGE, "-c", "curl --version | head -1"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0 and "curl " in r.stdout, (
            f"curl missing or broken: rc={r.returncode}, stderr={r.stderr!r}"
        )

        # USER root + /data is writable + can read a mode-0640 root-owned file
        # (the last assertion is the load-bearing one — mirrors the prod secret-read
        # pattern that crashed under USER 65532 in #153)
        data_cmd = (
            "id -u "
            "&& touch /data/.write-test "
            "&& rm /data/.write-test "
            "&& printf prod-parity > /tmp/fake-secret "
            "&& chmod 0640 /tmp/fake-secret "
            "&& chown 0:1000 /tmp/fake-secret "
            "&& cat /tmp/fake-secret"
        )
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/sh", self.IMAGE, "-c", data_cmd],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"USER/data check failed: {r.stderr}"
        lines = r.stdout.strip().split("\n")
        assert lines[0] == "0", f"container runs as UID {lines[0]!r}, expected 0 (root)"
        assert "prod-parity" in r.stdout, f"could not read 0640 root-owned file: {r.stdout!r}"


# =========================================================================
# Image metadata
# =========================================================================


@pytest.mark.mcp_metadata
class TestMCPImageMetadata:
    """Validate MCP image metadata (EXPOSE, labels)."""

    IMAGE = os.environ.get("TEST_MCP_IMAGE", "test-mcp-hackernews:latest")

    def test_mcp_image_exposes_8080(self):
        """MCP canary image exposes port 8080."""
        result = subprocess.run(
            [
                "docker", "inspect",
                "--format", "{{json .Config.ExposedPorts}}",
                self.IMAGE,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Image {self.IMAGE} not available locally")
        ports = json.loads(result.stdout)
        assert "8080/tcp" in ports, f"Port 8080 not exposed: {ports}"
