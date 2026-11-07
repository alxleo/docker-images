"""Acceptance tests for the disposable ARC runner image (run with IMAGE_REF set).

The pods run as UID 1001 with every capability dropped and no privilege
escalation, so every container here does too.
"""

import re

import pytest


@pytest.fixture(scope="module")
def runner(docker, image_ref):
    container = docker.start(*docker.HARDENED, "--entrypoint", "sleep", image_ref, "infinity")
    yield container
    container.remove()


def test_opengl_runtime_loads_offline(docker, image_ref):
    docker.run(
        "--network",
        "none",
        *docker.HARDENED,
        "--entrypoint",
        "python",
        image_ref,
        "-c",
        "import ctypes; ctypes.CDLL('libGL.so.1')",
    )


def test_runner_user_and_home(runner):
    runner.bash(
        'test "$(id -u)" = 1001; test "$(id -g)" = 1001; test "$HOME" = /home/runner; '
        'test -w "$HOME"; test ! -e /home/runner/k8s'
    )


def test_released_runner_and_its_node(runner):
    assert re.fullmatch(r"\d+\.\d+\.\d+", runner.exec("/home/runner/bin/Runner.Listener", "--version").strip())
    assert runner.exec("/home/runner/externals/node24/bin/node", "-e", "console.log(1 + 1)").strip() == "2"


@pytest.mark.parametrize(
    "command",
    [
        "git --version",
        "kwokctl --version",
        "uv --version",
        "jq --version",
        "python --version",
        "zsh --version",
        "bats --version",
        "chezmoi --version",
    ],
)
def test_inherited_tool_starts(runner, command):
    runner.exec(*command.split())


def test_zsh_at_both_paths_and_bats_runs_it(runner):
    runner.bash("test -x /bin/zsh; test -x /usr/bin/zsh")
    runner.bash("""printf '%s\\n' '@test "bats-ok" { run zsh -c "print -r zsh-ok"; [ "$output" = zsh-ok ]; }' > /tmp/ci.bats""")
    assert "ok 1 bats-ok" in runner.exec("bats", "/tmp/ci.bats")


def test_inherited_tool_tree_is_complete(runner):
    assert runner.exec("flux-schema", "version").strip() == runner.exec("mise", "current", "github:fluxcd/flux-schema").strip()
    assert runner.exec("mise", "ls", "--missing").strip() == ""


def test_project_mise_pins_install_beside_baseline(docker, image_ref, repo_root):
    script = (repo_root / "arc-runner" / "test-project-mise.sh").read_text()
    docker.run(*docker.HARDENED, "--entrypoint", "bash", image_ref, "-euo", "pipefail", input_text=script)
