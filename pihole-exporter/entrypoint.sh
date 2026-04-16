#!/bin/sh
set -eu

# eko/pihole-exporter v1.x reads PIHOLE_PASSWORD (env var for -pihole_password
# CLI flag). Pi-hole v5 accepted the same variable as an API token; Pi-hole v6
# uses session auth via POST /api/auth with the app-password. The exporter
# handles both v5/v6 at runtime — we just need the correct env var name.
#
# Secret file name kept as pihole_api_token for backwards compatibility with
# existing SOPS secrets (no rotation needed for the env-var rename).
if [ -f /run/secrets/pihole_api_token ]; then
    PIHOLE_PASSWORD="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' /run/secrets/pihole_api_token)"
    export PIHOLE_PASSWORD
elif [ -f /run/secrets/PIHOLE_PASSWORD ]; then
    PIHOLE_PASSWORD="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' /run/secrets/PIHOLE_PASSWORD)"
    export PIHOLE_PASSWORD
fi

exec /usr/local/bin/pihole-exporter "$@"
