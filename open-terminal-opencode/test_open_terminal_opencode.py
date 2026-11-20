"""Exercise OpenCode's native Agent Client Protocol in the built image."""

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
