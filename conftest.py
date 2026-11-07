"""Shared fixtures for the per-image tests in ``<image>/test_image.py``.

CI and ``just test-image`` build one image, export its reference as
``IMAGE_REF`` and run that image's ``test_image.py`` from the repository root.
Tests spell out every ``docker run`` flag themselves, so the security options an
image is tested under stay visible next to the assertion that depends on them.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent

# The hardening the unprivileged runner pods and most deployments apply.
HARDENED = ("--cap-drop", "ALL", "--security-opt", "no-new-privileges")


def _check(cmd: list[str], *, input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    """Run a command from the repository root and return its stdout, failing with its output."""
    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=None if env is None else {**os.environ, **env},
    )
    if result.returncode != 0:
        pytest.fail(
            f"exit {result.returncode}: {' '.join(cmd)}\n--- stdout\n{result.stdout}\n--- stderr\n{result.stderr}",
            pytrace=False,
        )
    return result.stdout


class Container:
    """A detached container that tests exec into; removed when its fixture ends."""

    def __init__(self, container_id: str) -> None:
        self.id = container_id

    def exec(self, *cmd: str) -> str:
        """Run a command as the image's own user, environment and working directory."""
        return _check(["docker", "exec", self.id, *cmd])

    def exec_result(self, *cmd: str) -> subprocess.CompletedProcess[str]:
        """Like ``exec`` but returns the result, for tests that expect a specific failure."""
        return subprocess.run(["docker", "exec", self.id, *cmd], capture_output=True, text=True, check=False)

    def bash(self, script: str) -> str:
        """Run a strict bash script inside the container."""
        return self.exec("bash", "-euo", "pipefail", "-c", script)

    def remove(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.id], capture_output=True, check=False)


class Docker:
    """Thin wrappers over the docker and host commands the image tests need."""

    HARDENED = HARDENED

    def __init__(self) -> None:
        self._started: list[Container] = []

    def run(self, *args: str, input_text: str | None = None) -> str:
        """``docker run --rm ARGS``; ``ARGS`` names the image and any flags explicitly."""
        return _check(["docker", "run", "--rm", *(["-i"] if input_text is not None else []), *args], input_text=input_text)

    def start(self, *args: str) -> Container:
        """``docker run -d ARGS``; the container is removed at teardown even if a test fails."""
        container = Container(_check(["docker", "run", "-d", *args]).strip())
        self._started.append(container)
        return container

    def inspect(self, image_ref: str, template: str) -> str:
        return _check(["docker", "inspect", image_ref, "--format", template]).strip()

    def host(self, *cmd: str, env: dict[str, str] | None = None) -> str:
        """Run a host-side command, such as a compose stack or a repository script, from the repo root."""
        return _check(list(cmd), env=env)

    def remove_started(self) -> None:
        for container in self._started:
            container.remove()
        self._started.clear()


@pytest.fixture(scope="session")
def image_ref() -> str:
    """The image under test. There is no fallback, so a test can never exercise a stale published image."""
    ref = os.environ.get("IMAGE_REF", "")
    if not ref:
        pytest.fail("IMAGE_REF must name the locally built image under test", pytrace=False)
    return ref


@pytest.fixture(scope="session")
def docker() -> Iterator[Docker]:
    helper = Docker()
    yield helper
    helper.remove_started()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT
