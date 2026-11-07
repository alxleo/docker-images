"""Acceptance tests for the LiteLLM image (run with IMAGE_REF set)."""


def test_runtime_offline(docker, image_ref, repo_root):
    script = (repo_root / "test" / "test-litellm-image.py").read_text()
    docker.run(
        "--network", "none", "--entrypoint", "/app/.venv/bin/python", image_ref, "-I", "-B", "-", input_text=script
    )


def test_cli_starts_offline(docker, image_ref):
    docker.run("--network", "none", "-e", "LITELLM_LOCAL_MODEL_COST_MAP=True", image_ref, "--help")
