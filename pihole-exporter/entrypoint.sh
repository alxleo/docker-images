#!/bin/sh
set -eu

if [ -d /run/secrets ]; then
    for f in /run/secrets/*; do
        [ -f "$f" ] || continue
        varname=$(basename "$f" | tr '[:lower:]' '[:upper:]')
        export "$varname"="$(cat "$f")"
    done
fi

exec /usr/local/bin/pihole-exporter "$@"
