"""Acceptance tests for the reading-room ARC runner image (run with IMAGE_REF set).

The pods run as UID 1001 with every capability dropped and no privilege
escalation, so every container here does too. Each baked tool is proven with
the network off: a job that finds what it needs in the image downloads nothing.
"""

import tomllib

import pytest

TOOLS = "python uv shellcheck cmake actionlint node pixi zig"


@pytest.fixture(scope="module")
def pins(repo_root):
    return tomllib.loads((repo_root / "reading-room-runner" / "mise.toml").read_text())


@pytest.fixture(scope="module")
def offline(docker, image_ref):
    container = docker.start("--network", "none", *docker.HARDENED, "--entrypoint", "sleep", image_ref, "infinity")
    yield container
    container.remove()


def test_runner_user_and_home(offline):
    offline.bash('test "$(id -u)" = 1001; test "$HOME" = /home/runner; test -w "$HOME"; test -x /home/runner/run.sh')


def test_project_mise_pins_install_offline(offline, pins):
    versions = " ".join(f"{tool}={version.removeprefix('v')}" for tool, version in pins["tools"].items())
    offline.bash(f"""
global_lock="$(sha256sum /opt/mise/mise.lock)"
node26="$(readlink /opt/mise/installs/node/26)"
project="$(mktemp -d)"
cp /opt/reading-room/mise.toml "$project/.mise.toml"
cp /opt/reading-room/mise.lock "$project/mise.lock"
cd "$project"
export MISE_LOCKED_SCOPES=project
mise trust --quiet .mise.toml
mise install --locked {TOOLS}
for pin in {versions}; do
    tool="${{pin%%=*}}"
    test "$(mise where "$tool")" = "/opt/mise/installs/$tool/${{pin#*=}}"
    # Each baked tool's directories belong to the job, as the base image's do.
    test -w "$(mise where "$tool")"
done
mise exec -- python --version | grep -Fx "Python {pins["tools"]["python"]}"
mise exec -- node --version | grep -Fx "v{pins["tools"]["node"]}"
mise exec -- zig version | grep -Fx "{pins["tools"]["zig"]}"
mise exec -- cmake --version | grep -Fq "cmake version {pins["tools"]["cmake"]}"
mise exec -- pixi --version | grep -Fq "{pins["tools"]["pixi"].removeprefix("v")}"
# The base image's own baseline and its global lock are untouched.
test "$(readlink /opt/mise/installs/node/26)" = "$node26"
test "$(sha256sum /opt/mise/mise.lock)" = "$global_lock"
test -z "$(cd / && mise ls --missing)"
""")


def test_qt_sdks_in_the_installer_layout(offline, pins):
    for version in (pins["env"]["QT_VERSION"], pins["env"]["QT_COMPAT_VERSION"]):
        offline.bash(f"""
test "$READING_ROOM_QT_SDKS" = /opt/reading-room-qt
case "$(uname -m)" in aarch64) folder=gcc_arm64 ;; x86_64) folder=gcc_64 ;; *) exit 1 ;; esac
prefix="$READING_ROOM_QT_SDKS/{version}/$folder"
test -f "$prefix/.reading-room-sdk-v2-complete"
test "$("$prefix/bin/qmake" -query QT_VERSION)" = "{version}"
test "$("$prefix/bin/qmake" -query QT_INSTALL_PREFIX)" = "$prefix"
for module in Core Qml Quick Svg; do test -d "$prefix/lib/cmake/Qt6$module"; done
test ! -w "$prefix"
""")


def test_rust_toolchain_matches_the_repository_offline(offline, repo_root):
    toolchain = tomllib.loads((repo_root / "reading-room-runner" / "rust-toolchain.toml").read_text())["toolchain"]
    channel = toolchain["channel"]
    offline.bash(f"""
test "$(command -v rustup)" = /opt/cargo/bin/rustup
test "$(command -v cargo)" = /opt/cargo/bin/cargo
project="$(mktemp -d)"
cp /opt/reading-room/rust-toolchain.toml "$project/"
cd "$project"
cargo --version | grep -Fq "cargo {channel} "
cargo clippy --version
cargo fmt --version
rustup target list --installed | grep -Fx {" ".join(f"-e {target}" for target in toolchain["targets"])}
cargo init --quiet --vcs none --name probe
cargo check --quiet --offline --target aarch64-unknown-linux-gnu
""")


def test_rust_homes_take_a_toolchain_bump_and_a_registry(docker, image_ref):
    """A later pin installs beside the baked toolchain instead of failing."""
    docker.run(
        *docker.HARDENED,
        "--entrypoint",
        "bash",
        image_ref,
        "-euo",
        "pipefail",
        "-c",
        """
test -w "$CARGO_HOME"
mkdir -p "$CARGO_HOME/registry/index"
baked="$(rustup default | cut -d' ' -f1)"
project="$(mktemp -d)"
cd "$project"
printf '%s\\n' '[toolchain]' 'channel = "1.97.0"' 'profile = "minimal"' >rust-toolchain.toml
cargo --version | grep -Fq 'cargo 1.97.0 '
rustup toolchain list | grep -Fq "$baked"
""",
    )


def test_zig_builds_an_arm64_helper_offline(offline):
    """The repository's helper build flags work with the baked Zig and no network."""
    offline.bash("""
scratch="$(mktemp -d)"
printf '%s\\n' '#include <math.h>' 'int main(void) { return (int)floor(0.5); }' >"$scratch/probe.c"
cd /opt/reading-room
MISE_TRUSTED_CONFIG_PATHS=/opt/reading-room mise exec zig -- zig cc -target aarch64-linux-musl -std=c11 -O2 \
    -Wall -Wextra -Werror -static -s -o "$scratch/probe" "$scratch/probe.c" -lm
test -s "$scratch/probe"
""")
