"""
Manifest schema validation — catches broken builds before Docker.

Validates mcp-images.json structure, mcp-defaults.json types,
cross-references between Caddyfile health_uri and defaults.
"""

import json
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = REPO_ROOT / "mcp"
MCP_IMAGES = json.loads((REPO_ROOT / "mcp-images.json").read_text())
MCP_FLEET = json.loads((REPO_ROOT / "mcp-fleet.json").read_text())
MCP_DEFAULTS = json.loads((REPO_ROOT / "mcp-defaults.json").read_text())
PUBLISHED_IMAGES = json.loads((REPO_ROOT / "images.json").read_text())
CUSTOM_IMAGES = json.loads(
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "discover-images.sh")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)

REQUIRED_IMAGE_FIELDS = {"name", "dockerfile", "build_args", "tag"}
REQUIRED_CUSTOM_FIELDS = {"name", "context", "tag"}


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

    def test_contract_files_are_all_referenced(self):
        declared = {entry["contract"] for entry in MCP_IMAGES if entry.get("contract")}
        declared.update(
            server["contract"]
            for server in MCP_FLEET["servers"]
            if server.get("contract")
        )
        present = {
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "mcp-contracts").glob("*.json")
        }
        assert declared == present, (
            f"MCP contract drift: missing={sorted(declared - present)}, "
            f"orphaned={sorted(present - declared)}"
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
            if "test_commands" in entry:
                assert isinstance(entry["test_commands"], list), (
                    f"{entry['name']}: test_commands must be a list"
                )
                assert all(
                    isinstance(command, str) and command
                    for command in entry["test_commands"]
                ), f"{entry['name']}: test_commands must contain non-empty strings"
            if "smoke_env" in entry:
                assert isinstance(entry["smoke_env"], list) and entry["smoke_env"], (
                    f"{entry['name']}: smoke_env must be a non-empty list"
                )
                declared_secrets = set(entry.get("secrets", []))
                for assignment in entry["smoke_env"]:
                    assert isinstance(assignment, str) and "=" in assignment, (
                        f"{entry['name']}: invalid smoke_env assignment"
                    )
                    name, value = assignment.split("=", 1)
                    assert name in declared_secrets, (
                        f"{entry['name']}: smoke_env {name} is not a declared secret"
                    )
                    assert value.startswith("test-"), (
                        f"{entry['name']}: smoke_env values must be obvious test fixtures"
                    )
            if "contract" in entry:
                assert isinstance(entry["contract"], str) and entry["contract"], (
                    f"{entry['name']}: contract must be a non-empty path"
                )
                assert (
                    not entry.get("secrets") or entry.get("smoke_env")
                ), f"{entry['name']}: contract requires a credential-safe smoke path"
                contract_path = REPO_ROOT / entry["contract"]
                assert contract_path.is_file(), (
                    f"{entry['name']}: contract does not exist: {entry['contract']}"
                )
                contract = json.loads(contract_path.read_text())
                assert contract.get("lock_version") == 1, (
                    f"{entry['name']}: unsupported MCP contract lock version"
                )
                assert contract.get("tools"), (
                    f"{entry['name']}: MCP contract must contain tools"
                )
                assert all(isinstance(tool, dict) for tool in contract["tools"]), (
                    f"{entry['name']}: MCP contract tools must be objects"
                )
                names = [tool.get("name") for tool in contract["tools"]]
                assert names == sorted(names) and len(names) == len(set(names)), (
                    f"{entry['name']}: MCP contract tool names must be unique and sorted"
                )
                assert all(
                    re.fullmatch(r"sha256:[0-9a-f]{64}", tool.get("input_schema_sha256", ""))
                    for tool in contract["tools"]
                ), f"{entry['name']}: MCP contract schema hashes must be SHA-256"


# =========================================================================
# Auto-discovered custom images
# =========================================================================


class TestCustomImagesManifest:
    """Schema validation for the auto-discovered custom image matrix."""

    def test_required_fields(self):
        for i, entry in enumerate(CUSTOM_IMAGES):
            missing = REQUIRED_CUSTOM_FIELDS - entry.keys()
            assert not missing, (
                f"Entry {i} ({entry.get('name', '???')}): missing {missing}"
            )

    def test_no_duplicate_names(self):
        names = [entry["name"] for entry in CUSTOM_IMAGES]
        dupes = [n for n in names if names.count(n) > 1]
        assert not dupes, f"Duplicate image names: {set(dupes)}"

    def test_tags_non_empty(self):
        for entry in CUSTOM_IMAGES:
            assert isinstance(entry["tag"], str) and entry["tag"], (
                f"{entry['name']}: tag must be a non-empty string"
            )

    def test_context_dirs_exist(self):
        for entry in CUSTOM_IMAGES:
            context_dir = REPO_ROOT / entry["context"]
            assert context_dir.is_dir(), (
                f"{entry['name']}: context dir '{entry['context']}' not found"
            )

    def test_watch_paths_are_valid(self):
        for entry in CUSTOM_IMAGES:
            assert isinstance(entry["watch_paths"], list), (
                f"{entry['name']}: watch_paths must be a list"
            )
            assert entry["watch_paths"] == sorted(set(entry["watch_paths"])), (
                f"{entry['name']}: watch_paths must be unique and sorted"
            )
            for path in entry["watch_paths"]:
                assert isinstance(path, str) and path, (
                    f"{entry['name']}: watch_paths must contain non-empty strings"
                )
                assert not Path(path).is_absolute() and ".." not in Path(path).parts, (
                    f"{entry['name']}: watch_paths must stay within the repository"
                )
                assert (REPO_ROOT / path).exists(), (
                    f"{entry['name']}: watch path does not exist: {path}"
                )

    def test_changed_image_selection(self):
        def selected(
            *paths,
            ci_changed=False,
            include_watch_paths=True,
            matrix_data=CUSTOM_IMAGES,
        ):
            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "scripts" / "select-custom-images.sh"),
                    json.dumps(matrix_data),
                    json.dumps(paths),
                    str(ci_changed).lower(),
                    str(include_watch_paths).lower(),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return {entry["name"] for entry in json.loads(result.stdout)}

        assert selected("mcp-contracts/mcp-hackernews.json") == set()
        assert selected("test/test-mcp-smoke.sh") == set()
        assert selected("test/test-native-mcp-image-smoke.sh") == {
            "mcp-reddit",
        }
        assert selected("test/test_custom_images.py") == {
            "caddy-cloudflare",
            "mcp-auth-proxy",
        }
        assert selected(
            "test/test_custom_images.py", include_watch_paths=False
        ) == set()
        assert selected(
            "caddy-cloudflare/Dockerfile", include_watch_paths=False
        ) == {"caddy-cloudflare"}
        assert selected("docs-hub/package.json") == {"docs-hub"}
        assert selected("README.md", ci_changed=True) == {
            entry["name"] for entry in CUSTOM_IMAGES
        }

        reddit = next(entry for entry in CUSTOM_IMAGES if entry["name"] == "mcp-reddit")
        for watch_path in ("./test/test-mcp-smoke.sh", "test/"):
            watched_reddit = {**reddit, "watch_paths": [watch_path]}
            assert selected(
                "test/test-mcp-smoke.sh", matrix_data=[watched_reddit]
            ) == {"mcp-reddit"}


class TestMCPPipelineRouting:
    """Keep fleet-only work out of the legacy image and full-stack pipelines."""

    @staticmethod
    def selected(*paths, ci_changed=False):
        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "select-mcp-pipelines.sh"),
                json.dumps(paths),
                str(ci_changed).lower(),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_toolhive_changes_use_the_focused_workflow(self):
        assert self.selected("mcp-fleet.json") == {"mcp": False, "e2e": False}
        assert self.selected("mcp-contracts/mcp-hackernews.json") == {
            "mcp": False,
            "e2e": False,
        }
        assert self.selected("mcp-contracts/mcp-jina.json") == {
            "mcp": False,
            "e2e": False,
        }
        assert self.selected("mcp-contracts/mcp-sequential-thinking.json") == {
            "mcp": False,
            "e2e": False,
        }
        assert self.selected("scripts/toolhive-fleet.py") == {
            "mcp": False,
            "e2e": False,
        }
        assert self.selected("test/test_toolhive_fleet.py") == {
            "mcp": False,
            "e2e": False,
        }

    def test_legacy_runtime_changes_select_only_required_pipelines(self):
        assert self.selected("test/test-mcp-smoke.sh") == {
            "mcp": True,
            "e2e": False,
        }
        assert self.selected("mcp/entrypoint.py") == {"mcp": True, "e2e": True}
        assert self.selected("caddy-cloudflare/Dockerfile") == {
            "mcp": False,
            "e2e": True,
        }

    def test_ci_uncertainty_fails_closed(self):
        assert self.selected("README.md", ci_changed=True) == {
            "mcp": True,
            "e2e": True,
        }


# =========================================================================
# images.json (public downstream contract)
# =========================================================================


class TestPublishedImageManifest:
    """Keep homelab's public image inventory aligned with build discovery."""

    def test_registry(self):
        assert PUBLISHED_IMAGES["registry"] == "ghcr.io/alxleo"

    def test_no_duplicate_names(self):
        names = PUBLISHED_IMAGES["images"]
        assert len(names) == len(set(names)), "images.json contains duplicate names"

    def test_exactly_matches_built_images(self):
        published = set(PUBLISHED_IMAGES["images"])
        built = {entry["name"] for entry in CUSTOM_IMAGES}
        built.update(entry["name"] for entry in MCP_IMAGES)
        assert published == built, (
            f"images.json drift: missing={sorted(built - published)}, "
            f"extra={sorted(published - built)}"
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
