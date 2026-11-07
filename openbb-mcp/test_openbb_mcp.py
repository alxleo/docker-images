"""Acceptance tests for the OpenBB MCP image (run with IMAGE_REF set)."""

import ast

EXPECTED_PACKAGES = {
    "openbb-core": "2.0.1",
    "openbb-mcp-server": "2.0.1",
    "openbb-sec": "2.0.0",
    "openbb-fred": "2.0.0",
    "openbb-ecb": "2.0.0",
    "openbb-imf": "3.0.0",
    "openbb-cboe": "2.0.0",
    "openbb-nasdaq": "2.0.0",
    "openbb-bls": "2.0.0",
    "openbb-yfinance": "2.1.0",
    "openbb-federal-reserve": "2.0.0",
}


def _python(docker, image_ref, code):
    return docker.run("--entrypoint", "python", image_ref, "-c", code).strip()


def test_pinned_provider_packages(docker, image_ref):
    installed = _python(
        docker,
        image_ref,
        "from importlib.metadata import version; "
        f"print({{name: version(name) for name in {sorted(EXPECTED_PACKAGES)!r}}})",
    )
    assert ast.literal_eval(installed) == EXPECTED_PACKAGES


def test_cache_directory_and_no_cli(docker, image_ref):
    _python(
        docker,
        image_ref,
        "from openbb_core.app.utils import get_user_cache_directory; "
        "assert get_user_cache_directory() == '/cache'; "
        "import importlib.util; assert importlib.util.find_spec('openbb_cli') is None",
    )


def test_serves_mcp_contract(docker, image_ref):
    docker.host("bash", "test/test-openbb-mcp-image.sh", env={"OPENBB_MCP_TEST_IMAGE": image_ref})
