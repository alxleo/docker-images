"""Acceptance tests for the FinRobot MCP image (run with IMAGE_REF set)."""


def test_providers_offline(docker, image_ref, repo_root):
    script = (repo_root / "test" / "test-finrobot-providers.py").read_text()
    docker.run("--network", "none", "--entrypoint", "python", image_ref, "-", input_text=script)


def test_route_allow_list(docker, image_ref):
    out = docker.run(
        "--entrypoint",
        "python",
        image_ref,
        "-c",
        "from finrobot_mcp import ROUTE_NAMES; "
        "assert ROUTE_NAMES[('POST','/api/compute/wacc')] == 'compute_wacc'; "
        "assert ('DELETE','/api/artifacts/{artifact_id}') not in ROUTE_NAMES; "
        "assert ('POST','/api/artifacts/{artifact_id}/view') not in ROUTE_NAMES; "
        "print(len(ROUTE_NAMES), 'allow-listed routes')",
    )
    assert "allow-listed routes" in out


def test_api_and_mcp_containers_together(docker, image_ref):
    docker.host("bash", "test/test-finrobot-mcp-image.sh", env={"FINROBOT_TEST_IMAGE": image_ref})
