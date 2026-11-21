"""Check the agent and GitHub CLI in the built Open Terminal image."""

import json


def test_opencode_initializes_acp_unprivileged(docker, image_ref):
    output = docker.run(
        "--network",
        "none",
        "--read-only",
        "--user",
        "1000:1000",
        "--tmpfs",
        "/tmp:mode=1777",
        "--tmpfs",
        "/home/user:uid=1000,gid=1000",
        "--env",
        "OPENCODE_DISABLE_MODELS_FETCH=true",
        "--entrypoint",
        "/bin/sh",
        image_ref,
        "-ec",
        r"""printf '%s\n' "$1" | timeout 20s opencode acp""",
        "sh",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                },
            }
        ),
    )
    reply = next(message for message in map(json.loads, output.splitlines()) if message.get("id") == 1)
    assert reply["result"]["protocolVersion"] == 1


def test_github_cli_supports_open_terminal_fields_unprivileged(docker, image_ref):
    fields = docker.run(
        "--network",
        "none",
        "--read-only",
        "--user",
        "1000:1000",
        "--env",
        "GH_PROMPT_DISABLED=1",
        "--entrypoint",
        "/bin/sh",
        image_ref,
        "-ec",
        """
        gh --version
        gh repo view --json 2>&1 || true
        gh issue list --json 2>&1 || true
        gh pr list --json 2>&1 || true
        """,
    ).splitlines()

    assert any(line.startswith("gh version ") for line in fields)
    assert {"nameWithOwner", "hasIssuesEnabled", "stateReason", "isDraft"} <= {line.strip() for line in fields}
