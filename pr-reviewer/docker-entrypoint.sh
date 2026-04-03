#!/bin/bash
set -e

# Fix ownership on writable volume-mounted directories.
# Named volumes retain root-owned files from before the UID 1000 migration.
# This runs as root, then drops to UID 1000 via gosu (postgres/redis pattern).

WRITABLE_DIRS="/app/state /app/repos /app/.claude /app/.codex"

for dir in $WRITABLE_DIRS; do
    if [[ -d "$dir" ]]; then
        owner=$(stat -c %u "$dir")
        if [[ "$owner" != "1000" ]]; then
            chown -R 1000:1000 "$dir"
        fi
    fi
done

exec gosu 1000 "$@"
