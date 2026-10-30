#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 1001
test ! -w /opt/mise
test ! -w /opt/mise/installs
baseline_npm="$(mise current npm:dependency-cruiser)"
baseline_python="$(mise current yamllint)"
project="$(mktemp -d)"
cp /opt/mise/mise.lock "$project/mise.lock"
cp -R /opt/mise/.mise "$project/.mise"
cd "$project"
printf '%s\n' 'min_version = "2026.10.23"' '[settings]' 'npm.package_manager = "aube"' \
    '[tools]' 'uv = "0.13.3"' "\"npm:dependency-cruiser\" = \"$baseline_npm\"" "yamllint = \"$baseline_python\"" > mise.toml
export MISE_DATA_DIR="$project/mise"
export MISE_CACHE_DIR="$project/mise-cache"
export MISE_SHARED_INSTALL_DIRS=/opt/mise/installs
export MISE_TRUSTED_CONFIG_PATHS="$project"
export MISE_LOCKED_SCOPES=project
test ! -e /opt/mise/installs/uv/0.13.3
mise lock --platform linux-x64,linux-arm64 uv
mise install --locked
test "$(mise where uv)" = "$MISE_DATA_DIR/installs/uv/0.13.3"
for tool in npm:dependency-cruiser yamllint; do
    case "$(mise where "$tool")" in
        /opt/mise/installs/*) ;;
        *) printf 'Prepared graph was not reused: %s\n' "$tool" >&2; exit 1 ;;
    esac
done
mise install --locked
mise exec -- uv --version | grep -Eq '^uv 0[.]13[.]3([[:space:]]|$)'
mise exec -- depcruise --version | grep -Fx "$baseline_npm"
mise exec -- yamllint --version | grep -Fx "yamllint $baseline_python"
mise exec -- kwokctl --version
