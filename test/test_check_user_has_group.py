"""
Regression tests for scripts/check-user-has-group.sh.

The hook runs only in pre-commit, which CI does not run, so these tests are
what keeps it agreeing with the repository's Dockerfiles.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "scripts" / "check-user-has-group.sh"


def run_hook(*paths):
    return subprocess.run(
        ["sh", str(HOOK), *map(str, paths)],
        capture_output=True,
        text=True,
        check=False,
    )


def write(tmp_path, text, name="Dockerfile"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_every_repository_dockerfile_passes():
    dockerfiles = sorted(REPO_ROOT.glob("*/Dockerfile")) + sorted(
        (REPO_ROOT / "mcp").glob("Dockerfile.*")
    )
    result = run_hook(*dockerfiles)
    assert result.returncode == 0, result.stdout


def test_user_creation_on_a_continuation_line_counts(tmp_path):
    dockerfile = write(
        tmp_path,
        "FROM debian\n"
        "RUN apt-get update \\\n"
        "    # create the runtime account\n"
        "    && addgroup --gid 1000 app \\\n"
        "    && adduser --uid 1000 --gid 1000 app\n"
        "USER 1000:1000\n",
    )
    assert run_hook(dockerfile).returncode == 0


def test_root_needs_no_group(tmp_path):
    dockerfile = write(tmp_path, "FROM debian\nUSER 0:0\nRUN true\nUSER 0\n")
    assert run_hook(dockerfile).returncode == 0


def test_named_user_is_accepted(tmp_path):
    assert run_hook(write(tmp_path, "FROM node:26-alpine\nUSER node\n")).returncode == 0


def test_numeric_user_without_group_fails_at_its_line(tmp_path):
    dockerfile = write(
        tmp_path,
        "FROM alpine\n"
        "RUN apk add --no-cache \\\n"
        "    curl\n"
        "USER 1000:1000\n",
    )
    result = run_hook(dockerfile)
    assert result.returncode == 1
    assert f"{dockerfile}:4 " in result.stdout


def test_user_created_in_an_earlier_stage_does_not_carry(tmp_path):
    dockerfile = write(
        tmp_path,
        "FROM alpine AS build\n"
        "RUN addgroup -g 1000 app && adduser -u 1000 -G app -S -D app\n"
        "FROM alpine\n"
        "USER 1000\n",
    )
    assert run_hook(dockerfile).returncode == 1


def test_hash_inside_a_command_is_not_a_comment(tmp_path):
    dockerfile = write(
        tmp_path,
        "FROM alpine\n"
        "RUN sed -i 's/#x/y/' /etc/profile \\\n"
        "    && addgroup -g 1000 app && adduser -u 1000 -G app -S -D app\n"
        "USER 1000\n",
    )
    assert run_hook(dockerfile).returncode == 0


def test_mention_in_a_comment_does_not_count(tmp_path):
    dockerfile = write(
        tmp_path,
        "FROM alpine\n"
        "# RUN addgroup -g 1000 app\n"
        "RUN true\n"
        "USER 1000\n",
    )
    assert run_hook(dockerfile).returncode == 1
