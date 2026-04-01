#!/bin/sh
set -eu

if [ -f /run/secrets/pihole_api_token ]; then
    PIHOLE_API_TOKEN="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' /run/secrets/pihole_api_token)"
    export PIHOLE_API_TOKEN
elif [ -f /run/secrets/PIHOLE_API_TOKEN ]; then
    PIHOLE_API_TOKEN="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' /run/secrets/PIHOLE_API_TOKEN)"
    export PIHOLE_API_TOKEN
fi

exec /usr/local/bin/pihole-exporter "$@"
