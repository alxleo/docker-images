"""Acceptance tests for the native Reddit MCP image (run with IMAGE_REF set)."""

import time
import urllib.request

import pytest


def _python(docker, image_ref, code):
    return docker.run("--entrypoint", "python", image_ref, "-c", code).strip()


def test_project_unit_suite(docker):
    docker.host("uv", "run", "--project", "mcp-reddit", "--frozen", "pytest", "mcp-reddit/tests/", "-v")


def test_python_line(docker, image_ref):
    assert _python(docker, image_ref, "import sys; print(sys.version)").startswith("3.14.")


def test_image_ships_the_locked_mcp_sdk(docker, image_ref):
    version = "from importlib.metadata import version; print(version('mcp'))"
    locked = docker.host("uv", "run", "--project", "mcp-reddit", "--frozen", "python", "-c", version).strip()
    assert _python(docker, image_ref, version) == locked


def test_no_proxy_layer(docker, image_ref):
    docker.run(
        "--entrypoint", "sh", image_ref, "-c", "! command -v node && ! command -v mcp-proxy && ! command -v mcp-filter"
    )


@pytest.fixture
def server(docker, image_ref):
    container = docker.start("-p", "18081:8080", image_ref)
    yield container
    container.remove()


def test_serves_mcp_contract(docker, server):
    for _ in range(20):
        try:
            with urllib.request.urlopen("http://127.0.0.1:18081/ping", timeout=2) as response:
                body = response.read().decode()
            break
        except OSError:
            time.sleep(1)
    else:
        pytest.fail("the server never answered /ping")
    assert body == "pong"
    docker.host("bash", "test/test-native-mcp-image-smoke.sh", server.id, "18081", "mcp-contracts/mcp-reddit.json")


def test_toolhive_fleet_runs_the_image(docker, image_ref):
    docker.host("bash", "test/test-toolhive-fleet.sh", env={"TOOLHIVE_REDDIT_IMAGE": image_ref})
