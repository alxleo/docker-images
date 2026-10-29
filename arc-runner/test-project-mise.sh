#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 1001
test ! -w /opt/mise
test ! -w /opt/mise/installs
project="$(mktemp -d)"
cd "$project"
printf '%s\n' '[tools]' 'uv = "0.13.3"' > mise.toml
export MISE_DATA_DIR="$project/mise"
export MISE_CACHE_DIR="$project/mise-cache"
export MISE_SHARED_INSTALL_DIRS=/opt/mise/installs
export MISE_TRUSTED_CONFIG_PATHS="$project"
test ! -e /opt/mise/installs/uv/0.13.3
mise install
test "$(mise where uv)" = "$MISE_DATA_DIR/installs/uv/0.13.3"
mise install
mise exec -- uv --version | grep -Eq '^uv 0[.]13[.]3([[:space:]]|$)'
mise exec -- kwokctl --version
