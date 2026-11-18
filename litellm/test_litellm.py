"""Acceptance tests for the LiteLLM image (run with IMAGE_REF set)."""

import ipaddress
import json
import uuid


def test_runtime_offline(docker, image_ref, repo_root):
    script = (repo_root / "test" / "test-litellm-image.py").read_text()
    docker.run(
        "--network", "none", "--entrypoint", "/app/.venv/bin/python", image_ref, "-I", "-B", "-", input_text=script
    )


def test_cli_starts_offline(docker, image_ref):
    docker.run("--network", "none", "-e", "LITELLM_LOCAL_MODEL_COST_MAP=True", image_ref, "--help")


def test_mcp_rest_admission(docker, image_ref, repo_root):
    script = (repo_root / "test" / "test-litellm-mcp-rest.py").read_text()
    docker.run(
        "--network", "none", "--entrypoint", "/app/.venv/bin/python", image_ref, "-I", "-B", "-", input_text=script
    )


def test_mcp_discovery_initialization(docker, image_ref, repo_root):
    script = (repo_root / "test" / "test-litellm-mcp-discovery.py").read_text()
    docker.run(
        "--network", "none", "--entrypoint", "/app/.venv/bin/python", image_ref, "-I", "-B", "-", input_text=script
    )


def test_offline_worker_does_not_block_catalogue_or_other_requests(docker, image_ref, repo_root):
    network = "litellm-discovery-" + uuid.uuid4().hex[:12]
    docker.host("docker", "network", "create", "--internal", network)
    try:
        info = json.loads(docker.host("docker", "network", "inspect", network))[0]
        subnet = ipaddress.ip_network(info["IPAM"]["Config"][0]["Subnet"])
        script = (repo_root / "test" / "test-litellm-model-discovery.py").read_text()
        output = docker.run(
            "--network",
            network,
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--pids-limit",
            "256",
            *docker.HARDENED,
            "-e",
            f"DISCOVERY_OFFLINE_ADDRESS={subnet[-2]}",
            "--entrypoint",
            "/app/.venv/bin/python",
            image_ref,
            "-I",
            "-B",
            "-",
            input_text=script,
        )
        print(output)
    finally:
        docker.host("docker", "network", "rm", network)
