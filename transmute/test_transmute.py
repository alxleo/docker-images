"""Acceptance tests for the Transmute image (run with IMAGE_REF set)."""


def test_converters_offline_read_only_unprivileged(docker, image_ref, repo_root):
    """Production runs it as a non-root, read-only, capability-free container with a bounded /tmp."""
    docker.run(
        "--network",
        "none",
        "--user",
        "1000:1000",
        "--read-only",
        *docker.HARDENED,
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--tmpfs",
        "/tmp:rw,size=512m,uid=1000,gid=1000",
        "-e",
        "HOME=/tmp",
        "-e",
        "DATA_DIR=/tmp/data",
        "--mount",
        f"type=bind,source={repo_root / 'test' / 'test-transmute-image.py'},target=/app/backend/test_image.py,readonly",
        "--workdir",
        "/app",
        "--entrypoint",
        "python",
        image_ref,
        "/app/backend/test_image.py",
    )
