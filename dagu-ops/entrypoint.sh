#!/bin/sh
# Entrypoint for dagu-ops: seed rclone config from Docker secret, then start Dagu.
#
# rclone needs a writable config file for OAuth token refresh.
# First run: copies secret into /root/.config/rclone/.
# Subsequent runs: skips unless credentials changed (client_id/client_secret).
set -eu

RCLONE_DIR="/root/.config/rclone"
RCLONE_CONF="${RCLONE_DIR}/rclone.conf"
SECRET_PATH="/run/secrets/rclone_conf"

mkdir -p "$RCLONE_DIR"

if [ -s "$SECRET_PATH" ]; then
  if [ ! -s "$RCLONE_CONF" ]; then
    cp "$SECRET_PATH" "$RCLONE_CONF"
    chmod 600 "$RCLONE_CONF"
    echo "[dagu-ops] Seeded rclone.conf from secret"
  else
    # Compare credential fields only (not tokens — those refresh automatically)
    OLD_CREDS=$(grep -E '^[[:space:]]*(client_id|client_secret)[[:space:]]*=' "$RCLONE_CONF" 2>/dev/null | sort)
    NEW_CREDS=$(grep -E '^[[:space:]]*(client_id|client_secret)[[:space:]]*=' "$SECRET_PATH" 2>/dev/null | sort)
    if [ "$OLD_CREDS" != "$NEW_CREDS" ]; then
      cp "$SECRET_PATH" "$RCLONE_CONF"
      echo "[dagu-ops] Credentials changed — re-seeded rclone.conf"
    else
      echo "[dagu-ops] rclone.conf exists, credentials unchanged"
    fi
    chmod 600 "$RCLONE_CONF"
  fi
else
  echo "[dagu-ops] No rclone secret at $SECRET_PATH — skipping seed"
fi

# Hand off to Dagu (or whatever CMD is passed)
exec "$@"
