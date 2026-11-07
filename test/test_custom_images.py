"""
Metadata checks for locally built MCP images.

Custom images keep their tests beside their Dockerfile, in
``<image>/test_<image>.py``, and run against the build under test (IMAGE_REF).
"""

import json
import os
import subprocess

import pytest

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
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"Image {self.IMAGE} not available locally")
        ports = json.loads(result.stdout)
        assert "8080/tcp" in ports, f"Port 8080 not exposed: {ports}"
