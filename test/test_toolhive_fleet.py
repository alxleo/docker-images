"""Contracts for the repository-owned ToolHive fleet."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "toolhive_fleet", ROOT / "scripts" / "toolhive-fleet.py"
)
assert SPEC and SPEC.loader
toolhive_fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(toolhive_fleet)


@pytest.fixture
def fleet():
    return toolhive_fleet.load_fleet(ROOT / "mcp-fleet.json")


def test_fleet_covers_published_and_direct_repository_mcps(fleet):
    assert toolhive_fleet.validate_fleet(fleet) == []
    assert len(fleet["servers"]) == 18
    assert sum(server["state"] == "ready" for server in fleet["servers"]) == 16
    assert sum(server["state"] == "legacy-wrapper" for server in fleet["servers"]) == 2


def test_runtime_and_package_drift_fail_closed(fleet):
    changed = copy.deepcopy(fleet)
    changed["runtimes"]["npx"] = "node:26-slim"
    context7 = next(server for server in changed["servers"] if server["name"] == "mcp-context7")
    context7["source"]["version"] = "3.2.6"

    errors = toolhive_fleet.validate_fleet(changed)

    assert any("requires apk" in error for error in errors)
    assert any("differs from image manifest" in error for error in errors)


def test_published_mcp_cannot_disappear_from_forward_fleet(fleet):
    changed = copy.deepcopy(fleet)
    changed["servers"] = [server for server in changed["servers"] if server["name"] != "mcp-context7"]

    errors = toolhive_fleet.validate_fleet(changed)

    assert any("missing published repository MCPs" in error and "mcp-context7" in error for error in errors)


def test_duplicate_ports_and_unsafe_custom_network_are_rejected(fleet):
    changed = copy.deepcopy(fleet)
    changed["servers"][1]["port"] = changed["servers"][0]["port"]
    searxng = next(server for server in changed["servers"] if server["name"] == "mcp-searxng")
    searxng["isolate_network"] = True

    errors = toolhive_fleet.validate_fleet(changed)

    assert any("duplicate ports" in error for error in errors)
    assert any("not enforceable with a custom Docker network" in error for error in errors)


def test_plan_is_explicit_and_contains_only_secret_references(fleet):
    brave = next(server for server in fleet["servers"] if server["name"] == "mcp-brave")

    argv = toolhive_fleet.workload_argv(fleet, brave)

    assert "--transport" in argv
    assert argv[argv.index("--transport") + 1] == "stdio"
    assert argv[argv.index("--runtime-image") + 1] == "node:26-alpine"
    assert argv[argv.index("--secret") + 1] == "BRAVE_API_KEY,target=BRAVE_API_KEY"
    assert not any("test-not-a-real-key" in arg for arg in argv)

    plan = toolhive_fleet.render_plan(fleet, [brave])
    assert plan["environment"] == {
        "TOOLHIVE_SECRETS_PROVIDER": "environment",
        "required_secret_variables": ["TOOLHIVE_SECRET_BRAVE_API_KEY"],
    }


def test_arxiv_plan_pins_python_constraint_and_mount_placeholder(fleet):
    arxiv = next(server for server in fleet["servers"] if server["name"] == "mcp-arxiv")

    argv = toolhive_fleet.workload_argv(fleet, arxiv)

    assert argv[argv.index("--runtime-image") + 1] == "python:3.14-slim"
    assert argv[argv.index("--build-with") + 1] == "mcp>=1.27,<2"
    assert argv[argv.index("--volume") + 1] == "${ARXIV_DATA_DIR}:/data/papers"
    assert argv[-3:] == ["--", "--storage-path", "/data/papers"]


def test_jina_uses_direct_remote_with_secret_backed_authorization(fleet):
    jina = next(server for server in fleet["servers"] if server["name"] == "mcp-jina")

    argv = toolhive_fleet.workload_argv(fleet, jina)

    assert "mcp-remote" not in " ".join(argv)
    assert argv[-1] == "https://mcp.jina.ai/v1"
    flag = argv.index("--remote-forward-headers-secret")
    assert argv[flag + 1] == "Authorization=JINA_AUTHORIZATION"
    assert "--secret" not in argv
    assert toolhive_fleet.render_plan(fleet, [jina])["environment"][
        "required_secret_variables"
    ] == ["TOOLHIVE_SECRET_JINA_AUTHORIZATION"]


def test_exec_requires_runtime_environment(fleet, monkeypatch):
    searxng = next(server for server in fleet["servers"] if server["name"] == "mcp-searxng")
    monkeypatch.delenv("SEARXNG_URL", raising=False)

    with pytest.raises(toolhive_fleet.FleetError, match="SEARXNG_URL is unset"):
        toolhive_fleet.workload_argv(fleet, searxng, resolve_environment=True)


def test_oci_workloads_use_distinct_target_ports(fleet):
    oci_servers = [server for server in fleet["servers"] if server["source"]["type"] == "oci"]
    target_ports = [server["source"]["target_port"] for server in oci_servers]

    assert len(target_ports) == len(set(target_ports))
    assert not set(target_ports) & {server["port"] for server in fleet["servers"]}
    for server in oci_servers:
        argv = toolhive_fleet.workload_argv(fleet, server)
        target_port = str(server["source"]["target_port"])
        assert argv[argv.index("--target-port") + 1] == target_port
        assert f"MCP_PORT={target_port}" in argv


def test_oci_source_can_be_overridden_for_exact_local_image_testing(fleet):
    reddit = next(server for server in fleet["servers"] if server["name"] == "mcp-reddit")

    argv = toolhive_fleet.workload_argv(
        fleet,
        reddit,
        source_override="docker-images-local/mcp-reddit:test",
    )

    assert argv[-1] == "docker-images-local/mcp-reddit:test"


def test_tool_override_is_rendered_as_repeated_filter_flags(fleet):
    hackernews = next(server for server in fleet["servers"] if server["name"] == "mcp-hackernews")

    argv = toolhive_fleet.workload_argv(
        fleet,
        hackernews,
        tools=["getTopStories", "getNewStories"],
    )

    assert [argv[index + 1] for index, arg in enumerate(argv) if arg == "--tools"] == [
        "getTopStories",
        "getNewStories",
    ]


def test_non_loopback_bind_requires_an_origin_allowlist(fleet):
    hackernews = next(server for server in fleet["servers"] if server["name"] == "mcp-hackernews")

    with pytest.raises(toolhive_fleet.FleetError, match="requires an allowed origin"):
        toolhive_fleet.workload_argv(fleet, hackernews, host="172.20.0.1")

    argv = toolhive_fleet.workload_argv(
        fleet,
        hackernews,
        host="172.20.0.1",
        allowed_origins=["https://mcp.example.test"],
    )
    assert argv[argv.index("--allowed-origins") + 1] == "https://mcp.example.test"
