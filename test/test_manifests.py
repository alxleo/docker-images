"""
Manifest schema validation — catches broken builds before Docker.

Validates mcp-images.json structure, mcp-defaults.json types,
cross-references between Caddyfile health_uri and defaults.
"""

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = REPO_ROOT / "mcp"
MCP_IMAGES = json.loads((REPO_ROOT / "mcp-images.json").read_text())
MCP_DEFAULTS = json.loads((REPO_ROOT / "mcp-defaults.json").read_text())

REQUIRED_IMAGE_FIELDS = {"name", "dockerfile", "build_args", "tag"}


# =========================================================================
# mcp-images.json
# =========================================================================


class TestMCPImagesManifest:
    """Schema validation for the MCP image build matrix."""

    def test_required_fields(self):
        for i, entry in enumerate(MCP_IMAGES):
            missing = REQUIRED_IMAGE_FIELDS - entry.keys()
            assert not missing, (
                f"Entry {i} ({entry.get('name', '???')}): missing {missing}"
            )

    def test_no_duplicate_names(self):
        names = [entry["name"] for entry in MCP_IMAGES]
        dupes = [n for n in names if names.count(n) > 1]
        assert not dupes, f"Duplicate image names: {set(dupes)}"

    def test_dockerfile_refs_exist(self):
        for entry in MCP_IMAGES:
            dockerfile = MCP_DIR / entry["dockerfile"]
            assert dockerfile.exists(), (
                f"{entry['name']}: {entry['dockerfile']} not found in mcp/"
            )

    def test_optional_fields_types(self):
        for entry in MCP_IMAGES:
            if "description" in entry:
                assert isinstance(entry["description"], str) and entry["description"], (
                    f"{entry['name']}: description must be a non-empty string"
                )
            if "secrets" in entry:
                assert isinstance(entry["secrets"], list), (
                    f"{entry['name']}: secrets must be a list"
                )
                for secret in entry["secrets"]:
                    assert isinstance(secret, str) and secret, (
                        f"{entry['name']}: each secret must be a non-empty string"
                    )


# =========================================================================
# mcp-defaults.json
# =========================================================================


class TestMCPDefaults:
    """Schema validation for runtime defaults consumed by downstream."""

    def test_health_path(self):
        assert isinstance(MCP_DEFAULTS["health_path"], str)
        assert MCP_DEFAULTS["health_path"].startswith("/")

    def test_health_port(self):
        assert isinstance(MCP_DEFAULTS["health_port"], int)
        assert MCP_DEFAULTS["health_port"] > 0

    def test_mcp_endpoint(self):
        assert isinstance(MCP_DEFAULTS["mcp_endpoint"], str)
        assert MCP_DEFAULTS["mcp_endpoint"].startswith("/")


# =========================================================================
# Cross-references
# =========================================================================


class TestCrossReferences:
    """Validate consistency between manifest files and Caddyfiles."""

    def test_caddyfile_health_uri_matches_defaults(self):
        """Every health_uri in test Caddyfile must match mcp-defaults.json."""
        caddyfile = (REPO_ROOT / "test" / "Caddyfile.mcp-e2e").read_text()
        health_uris = re.findall(r"health_uri\s+(\S+)", caddyfile)
        assert health_uris, "No health_uri directives found in Caddyfile"
        for uri in health_uris:
            assert uri == MCP_DEFAULTS["health_path"], (
                f"Caddyfile health_uri '{uri}' doesn't match "
                f"mcp-defaults.json health_path '{MCP_DEFAULTS['health_path']}'"
            )

    def test_example_compose_valid_yaml(self):
        """examples/docker-compose.yml must be valid YAML."""
        compose_path = REPO_ROOT / "examples" / "docker-compose.yml"
        content = compose_path.read_text()
        data = yaml.safe_load(content)
        assert isinstance(data, dict), "Compose file must be a YAML mapping"
        assert "services" in data, "Compose file must have a 'services' key"
