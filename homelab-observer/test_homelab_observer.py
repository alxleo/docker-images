"""Acceptance tests for the observer MCP image (run with IMAGE_REF set)."""

import json


def test_server_dependencies_import(docker, image_ref):
    docker.run(
        "--entrypoint",
        "python",
        image_ref,
        "-c",
        "from mcp.server.fastmcp import FastMCP; import pydantic, yaml, requests; "
        "assert FastMCP and pydantic and yaml and requests",
    )


def test_default_command_starts_the_server(docker, image_ref):
    cmd = json.loads(docker.inspect(image_ref, "{{json .Config.Cmd}}"))
    assert "/app/services/mcp-homelab-observer/server.py" in cmd
