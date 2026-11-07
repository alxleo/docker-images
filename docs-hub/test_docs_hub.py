"""Acceptance tests for the docs hub image (run with IMAGE_REF set)."""


def _read_only_bind(source, target):
    return f"type=bind,source={source},target={target},readonly"


def test_unit_suite_and_astro_check_pass_in_image(docker, image_ref, repo_root):
    docs_hub = repo_root / "docs-hub"
    docker.run(
        "--entrypoint",
        "/bin/sh",
        "--mount",
        _read_only_bind(docs_hub / "tests", "/app/tests"),
        "--mount",
        _read_only_bind(docs_hub / "test-config", "/app/test-config"),
        "--mount",
        _read_only_bind(docs_hub / "Dockerfile", "/app/Dockerfile"),
        image_ref,
        "-ec",
        "mkdir -p /state/.astro /state/.astro-cache && ln -s /app/node_modules /state/node_modules"
        " && npm test && npm run check",
    )


def test_runtime_serves_as_host_and_root_users(docker, image_ref):
    docker.host("bash", "docs-hub/tests/runtime-smoke.sh", image_ref)
