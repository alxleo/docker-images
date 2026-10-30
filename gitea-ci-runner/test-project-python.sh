#!/usr/bin/env bash
set -euo pipefail
test ! -w /opt/mise/installs
project="$(mktemp -d)"
cp /opt/mise/mise.lock "$project/mise.lock"
cd "$project"
printf '%s\n' '[tools]' 'python = "3.13.18"' >mise.toml
export MISE_CONFIG_DIR="$project/config" MISE_DATA_DIR="$project/mise" MISE_CACHE_DIR="$project/cache"
export MISE_GLOBAL_CONFIG_FILE=/opt/mise/config.toml MISE_SHARED_INSTALL_DIRS=/opt/mise/installs
export MISE_TRUSTED_CONFIG_PATHS="$project" MISE_LOCKED_SCOPES=project
mise lock --platform linux-x64,linux-arm64 python
mise install --locked
test "$(mise where python)" = "$MISE_DATA_DIR/installs/python/3.13.18"
for tool in semgrep yamllint pipx:ansible-core; do
    case "$(mise where "$tool")" in
    /opt/mise/installs/*) ;;
    *)
        printf 'Prepared Python tool was not reused: %s\n' "$tool" >&2
        exit 1
        ;;
    esac
done
mise install --locked
mise exec -- python --version | grep -Fx 'Python 3.13.18'
mise exec -- yamllint --version
