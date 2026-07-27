#!/bin/sh
set -eu

readonly state_dir="${DOCS_HUB_STATE_DIR:-/state}"

current_uid=$(id -u)
if [ "$current_uid" = "0" ]; then
    chown 1000:1000 "$state_dir"
    exec su-exec 1000:1000 node /app/server/controller.mjs
fi

exec node /app/server/controller.mjs
