"""Acceptance tests for Caddy with the Cloudflare DNS and Sablier modules (run with IMAGE_REF set)."""

import pytest


@pytest.mark.parametrize("module", ["dns.providers.cloudflare", "http.handlers.sablier"])
def test_module_compiled_in(docker, image_ref, module):
    assert module in docker.run(image_ref, "caddy", "list-modules").split()


def test_caddy_version(docker, image_ref):
    assert docker.run(image_ref, "caddy", "version").strip().startswith("v2.")


def test_validates_production_patterns(docker, image_ref, repo_root):
    docker.run(
        "-v",
        f"{repo_root / 'test'}:/test",
        image_ref,
        "caddy",
        "validate",
        "--config",
        "/test/Caddyfile.test",
        "--adapter",
        "caddyfile",
    )


def test_routes_production_patterns(docker, image_ref):
    """Snippet import, handle_path stripping, handle exclusivity, health and redir fallback."""
    compose = ("docker", "compose", "--project-directory", "test", "-f", "test/docker-compose.test.yml")
    env = {"IMAGE_REF": image_ref}
    try:
        docker.host(*compose, "up", "-d", "--wait", env=env)
        docker.host("bash", "test/test-caddy-routing.sh")
    finally:
        docker.host(*compose, "down", env=env)
