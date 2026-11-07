"""Acceptance tests for the mcp-auth-proxy build (run with IMAGE_REF set)."""

import subprocess


def test_session_fields_keep_512_wide_columns(docker, image_ref, tmp_path):
    """Regression check for sigbit/mcp-auth-proxy#111, fixed upstream in v2.9.x.

    Go interns identical struct-tag literals, so the count of ``size:512`` copies
    is not load-bearing. What matters is that at least one is present and that no
    session-storage field has shrunk back to ``size:255``.
    """
    container_id = docker.host("docker", "create", image_ref).strip()
    binary = tmp_path / "mcp-auth-proxy"
    try:
        docker.host("docker", "cp", f"{container_id}:/usr/local/bin/mcp-auth-proxy", str(binary))
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, check=False)
    contents = binary.read_bytes()
    assert contents.count(b"size:512") >= 1, "no size:512 tags: upstream may have removed the wider columns"
    assert contents.count(b"size:255") == 0, "a session-storage field regressed to size:255"


def _sh(docker, image_ref, script):
    # Override the ENTRYPOINT (the proxy binary): otherwise the script would be
    # passed to the proxy as flags and a missing shell would go unnoticed.
    return docker.run("--entrypoint", "/bin/sh", image_ref, "-c", script)


def test_shell_runs(docker, image_ref):
    assert _sh(docker, image_ref, "echo shell-ok").strip() == "shell-ok"


def test_ca_bundle_present(docker, image_ref):
    """OAuth identity providers are reached over TLS."""
    assert int(_sh(docker, image_ref, "wc -c </etc/ssl/certs/ca-certificates.crt")) > 100_000


def test_curl_for_healthchecks(docker, image_ref):
    assert _sh(docker, image_ref, "curl --version | head -1").startswith("curl ")


def test_root_reads_0640_secret_mount_and_writes_data(docker, image_ref):
    """Compose mounts secrets 0640 and owned by the host user; only root can read them (see #153)."""
    out = _sh(
        docker,
        image_ref,
        "id -u && touch /data/.write-test && rm /data/.write-test && printf prod-parity > /tmp/fake-secret"
        " && chmod 0640 /tmp/fake-secret && chown 0:1000 /tmp/fake-secret && cat /tmp/fake-secret",
    )
    uid, secret = out.split("\n", 1)
    assert uid == "0"
    assert secret == "prod-parity"
