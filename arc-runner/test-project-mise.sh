#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 1001
# The job owns the tool tree: the image's own settings are the whole contract, so
# no data directory, PATH or environment-file override is needed to install.
test "$MISE_DATA_DIR" = /opt/mise
test "$MISE_CACHE_DIR" = /home/runner/_work/.mise-cache
test -w /opt/mise/installs
test -w /opt/mise/installs/uv
test -w /opt/mise/shims
test ! -w /opt/mise/config.toml
test ! -w /opt/mise/mise.lock
global_lock="$(sha256sum /opt/mise/mise.lock)"
baseline_uv="$(mise current uv)"
baseline_npm="$(mise current npm:dependency-cruiser)"
baseline_python="$(mise current yamllint)"
project="$(mktemp -d)"
cp /opt/mise/mise.lock "$project/mise.lock"
cp -R /opt/mise/.mise "$project/.mise"
cd "$project"
printf '%s\n' 'min_version = "2026.10.23"' '[settings]' 'npm.package_manager = "aube"' \
    '[tools]' 'uv = "0.13.3"' "\"npm:dependency-cruiser\" = \"$baseline_npm\"" >mise.toml
sed -n '/^yamllint = /p' /opt/mise/config.toml >>mise.toml
export MISE_TRUSTED_CONFIG_PATHS="$project"
export MISE_LOCKED_SCOPES=project
test ! -e /opt/mise/installs/uv/0.13.3
mise lock --platform linux-x64,linux-arm64 uv
mise install --locked
# The changed pin lands beside the baseline in the shared tree, which stays intact.
test "$(mise where uv)" = /opt/mise/installs/uv/0.13.3
test -d "/opt/mise/installs/uv/$baseline_uv"
for tool in npm:dependency-cruiser yamllint; do
    case "$(mise where "$tool")" in
    /opt/mise/installs/*) ;;
    *)
        printf 'Prepared graph was not reused: %s\n' "$tool" >&2
        exit 1
        ;;
    esac
done
mise install --locked
test "$(sha256sum /opt/mise/mise.lock)" = "$global_lock"
# A step that has no mise settings of its own reaches the pin through the shim on PATH.
uv --version | grep -Eq '^uv 0[.]13[.]3([[:space:]]|$)'
(cd / && uv --version | grep -Fq "uv $baseline_uv")
mise exec -- uv --version | grep -Eq '^uv 0[.]13[.]3([[:space:]]|$)'
mise exec -- depcruise --version | grep -Fx "$baseline_npm"
mise exec -- yamllint --version | grep -Fx "yamllint $baseline_python"
mise exec -- kwokctl --version
