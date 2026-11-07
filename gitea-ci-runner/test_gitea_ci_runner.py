"""Acceptance tests for the Gitea Actions job image (run with IMAGE_REF set)."""

import json
import re
import shlex

import pytest

# Every prepared CLI must start as the job user. Commands, not versions: the
# pins live in mise.toml and mise.lock, which `mise ls --missing` checks.
TOOL_COMMANDS = [
    "uv --version",
    "mise --version",
    "pre-commit --version",
    "actions-up --version",
    "just --version",
    "zsh --version",
    "bats --version",
    "chezmoi --version",
    "ruff --version",
    "caddy version",
    "tofu version",
    "shellcheck --version",
    "shfmt --version",
    "yamllint --version",
    "actionlint -version",
    "zizmor --version",
    "cue version",
    "semgrep --version",
    "lychee --version",
    "gitleaks version",
    "hadolint --version",
    "trivy --version",
    "conftest --version",
    "d2 version",
    "jq --version",
    "yq --version",
    "ansible --version",
    "json2ts --help",
    "depcruise --version",
    "axe --version",
    "jscpd --version",
    "helm version --short",
    "kubectl version --client=true",
    "flux --version",
    "talosctl version --client",
    "hubble version",
    "openobserve-cli version",
    "flux-operator-mcp serve --help",
    "mcpjam --version",
    "terraform-docs version",
    "tflint --version",
    "sops --version",
    "age --version",
    "bao version",
    "cloudflared version",
    "restic version",
    "gh --version",
    "kwokctl --version",
    "kyverno version",
    "kube-linter version",
    "pluto version",
]

NPM_CLIS = ["json2ts", "depcruise", "axe", "jscpd", "actions-up"]


@pytest.fixture(scope="module")
def job(docker, image_ref):
    """A job container with the writable workspace tmpfs the runner provides."""
    container = docker.start(
        "--tmpfs",
        "/workspace:rw,uid=1000,gid=1000,mode=0755",
        "--entrypoint",
        "sleep",
        image_ref,
        "infinity",
    )
    yield container
    container.remove()


def test_job_user_and_writable_paths(job):
    job.bash(
        'test "$(id -u)" = 1000; test "$(id -g)" = 1000; test "$HOME" = /home/ubuntu; '
        'test -w "$HOME"; test -w /workspace; touch /workspace/.workspace-smoke'
    )


def test_no_prepared_tool_is_missing(job):
    assert job.exec("mise", "ls", "--missing").strip() == ""


@pytest.mark.parametrize(
    ("command", "pattern"),
    [
        ("python3.13 --version", r"^Python 3\.13\."),
        ("python3.14 --version", r"^Python 3\.14\."),
        ("node24 --version", r"^v24\."),
        ("node26 --version", r"^v26\."),
        ("npm24 --version", r"^\d"),
        ("npm26 --version", r"^\d"),
    ],
)
def test_runtime_lines(job, command, pattern):
    assert re.match(pattern, job.exec(*command.split()))


def test_bun_runs_code(job):
    assert job.exec("bun", "-e", "console.log(1+1)").strip() == "2"


@pytest.mark.parametrize("command", TOOL_COMMANDS)
def test_prepared_tool_starts(job, command):
    job.exec(*command.split())


@pytest.mark.parametrize("cli", NPM_CLIS)
def test_npm_cli_on_path(job, cli):
    job.bash(f"command -v {cli}")


def test_zsh_at_both_paths_and_bats_runs_it(job):
    job.bash("test -x /bin/zsh; test -x /usr/bin/zsh")
    test_file = '@test "bats-ok" { run zsh -c "print -r zsh-ok"; [ "$output" = zsh-ok ]; }'
    job.bash(f"printf '%s\\n' {shlex.quote(test_file)} > /tmp/ci.bats")
    assert "ok 1 bats-ok" in job.exec("bats", "/tmp/ci.bats")


def test_python_stdlib_extensions(job):
    job.exec("python3", "-c", "import bz2,ctypes,json,lzma,pathlib,ssl,sqlite3,tarfile,zlib")


def test_c_and_cpp_toolchains(job):
    c_source = '#include <stdio.h>\nint main(void) { puts("c-ok"); return 0; }\n'
    cpp_source = '#include <filesystem>\nint main() { return std::filesystem::exists("/tmp") ? 0 : 1; }\n'
    job.bash(
        f"printf '%s' {shlex.quote(c_source)} > /tmp/ci.c; cc -Wall -Werror /tmp/ci.c -o /tmp/ci-c; "
        f"printf '%s' {shlex.quote(cpp_source)} > /tmp/ci.cpp; c++ -std=c++17 -Wall -Werror /tmp/ci.cpp -o /tmp/ci-cpp; "
        "/tmp/ci-cpp"
    )
    assert job.exec("/tmp/ci-c").strip() == "c-ok"


def test_zstd_cache_round_trip(job):
    job.bash(
        "printf '%s\\n' cache > /tmp/ci-cache; tar -cf /tmp/ci.tar -C /tmp ci-cache; "
        "zstd -q -f /tmp/ci.tar -o /tmp/ci.tar.zst; zstd -q -t /tmp/ci.tar.zst"
    )


def test_docker_client_plugins(job):
    compose_file = "services:\n  check:\n    image: ubuntu:24.04\n"
    job.bash(
        "git lfs version; docker buildx version; command -v docker; docker compose version; "
        f"printf '%s' {shlex.quote(compose_file)} > /tmp/compose.yml; docker compose -f /tmp/compose.yml config >/dev/null"
    )


def test_flux_schema_validates_against_extracted_crd(job):
    assert job.exec("flux-schema", "version").strip() == job.exec("mise", "current", "github:fluxcd/flux-schema").strip()
    crd = {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {"name": "widgets.test.example"},
        "spec": {
            "group": "test.example",
            "names": {"kind": "Widget", "plural": "widgets"},
            "scope": "Namespaced",
            "versions": [
                {
                    "name": "v1",
                    "served": True,
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {
                                "spec": {
                                    "type": "object",
                                    "required": ["count"],
                                    "properties": {"count": {"type": "integer"}},
                                }
                            },
                        }
                    },
                }
            ],
        },
    }
    job.bash(
        "mkdir -p /tmp/flux-schema-smoke; cd /tmp/flux-schema-smoke; "
        f"printf '%s\\n' {shlex.quote(json.dumps(crd))} > crd.json; flux-schema extract crd crd.json -d schemas"
    )

    def validate(count):
        widget = {"apiVersion": "test.example/v1", "kind": "Widget", "metadata": {"name": "smoke"}, "spec": {"count": count}}
        return job.exec_result(
            "bash",
            "-c",
            f"cd /tmp/flux-schema-smoke; printf '%s\\n' {shlex.quote(json.dumps(widget))}"
            " | flux-schema validate --schema-location ./schemas",
        )

    valid = validate(1)
    assert valid.returncode == 0, valid.stderr
    invalid = validate("invalid")
    assert invalid.returncode == 1, (invalid.returncode, invalid.stdout, invalid.stderr)


def test_source_label(docker, image_ref):
    label = docker.inspect(image_ref, '{{ index .Config.Labels "org.opencontainers.image.source" }}')
    assert label == "https://github.com/alxleo/docker-images"


def test_environment_carries_no_credentials(docker, image_ref):
    env = docker.inspect(image_ref, "{{json .Config.Env}}")
    assert not re.search(r"token|password|secret|credential", env, re.IGNORECASE)


def test_project_python_pins_install_beside_baseline(docker, image_ref, repo_root):
    script = (repo_root / "gitea-ci-runner" / "test-project-python.sh").read_text()
    docker.run(*docker.HARDENED, "--entrypoint", "bash", image_ref, "-euo", "pipefail", input_text=script)
