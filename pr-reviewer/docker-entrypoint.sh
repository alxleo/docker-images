#!/bin/bash
set -e

# Fix ownership on writable volume-mounted directories.
# Named volumes retain root-owned files from before the UID 1000 migration.
# This runs as root, then drops to UID 1000 via gosu (postgres/redis pattern).

WRITABLE_DIRS="/app/state /app/repos /app/plugins /app/.claude /app/.codex /app/.gemini"

for dir in $WRITABLE_DIRS; do
    if [[ -d "$dir" ]]; then
        bad=$(find "$dir" \( ! -uid 1000 -o ! -gid 1000 \) -print -quit)
        if [[ -n "$bad" ]]; then
            chown -R 1000:1000 "$dir"
        fi
    fi
done

# tini handles PID 1 duties (zombie reaping, signal forwarding).
# Without it, python as PID 1 ignores SIGTERM → docker stop hangs 10s then SIGKILLs.
exec tini -- gosu 1000 "$@"
