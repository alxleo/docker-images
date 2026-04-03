#!/bin/bash
# Entrypoint for restic-scheduler: generate crontab from env vars, run supercronic.
#
# Supports two modes:
#   1. Env vars: set BACKUP_CRON, PRUNE_CRON, CHECK_CRON (any combination)
#   2. Custom crontab: mount file at /etc/supercronic/crontab
#
# Unlike resticker, all three cron types run in one container.
set -euo pipefail

CRONTAB="/etc/supercronic/crontab"

# Run any pre-entrypoint hook (e.g., seed-rclone.sh sets up rclone config)
if [[ -x /scripts/pre-entrypoint.sh ]]; then
  /scripts/pre-entrypoint.sh
fi

# Init restic repo if needed (skip if SKIP_INIT is set)
skip_init=$(echo "${SKIP_INIT:-false}" | tr '[:upper:]' '[:lower:]')
if [[ "$skip_init" != "true" ]]; then
  echo "[scheduler] Checking repository '${RESTIC_REPOSITORY:-<not set>}'..."
  if restic snapshots --no-lock -q >/dev/null 2>&1; then
    echo "[scheduler] Repository found."
  else
    echo "[scheduler] Repository not found, initializing..."
    restic init
    echo "[scheduler] Repository initialized."
  fi
fi

# Generate crontab from env vars (if no custom crontab mounted)
if [[ ! -s "$CRONTAB" ]]; then
  echo "[scheduler] Generating crontab from environment variables..."
  : > "$CRONTAB"

  if [[ -n "${BACKUP_CRON:-}" ]]; then
    echo "${BACKUP_CRON} /usr/local/bin/backup" >> "$CRONTAB"
    echo "[scheduler] Backup scheduled: ${BACKUP_CRON}"
  fi

  if [[ -n "${PRUNE_CRON:-}" ]]; then
    echo "${PRUNE_CRON} /usr/local/bin/prune" >> "$CRONTAB"
    echo "[scheduler] Prune scheduled: ${PRUNE_CRON}"
  fi

  if [[ -n "${CHECK_CRON:-}" ]]; then
    echo "${CHECK_CRON} /usr/local/bin/check" >> "$CRONTAB"
    echo "[scheduler] Check scheduled: ${CHECK_CRON}"
  fi

  if [[ ! -s "$CRONTAB" ]]; then
    echo "[scheduler] ERROR: No cron schedules configured. Set BACKUP_CRON, PRUNE_CRON, or CHECK_CRON." >&2
    exit 1
  fi
else
  echo "[scheduler] Using mounted crontab at ${CRONTAB}"
fi

echo "[scheduler] Starting supercronic..."
exec supercronic "$CRONTAB"
