#!/bin/sh
# Fail pre-commit if a Dockerfile declares `USER <numeric>` without either
# (a) creating a matching group/user earlier in the same Dockerfile, or
# (b) switching to a named user that the base image is known to provide.
#
# Background: `python:3.13-alpine` and `alpine:*` bases do NOT ship a
# user at uid=1000. `USER 1000` on those bases makes the process run
# with gid=0 (root), and Docker secrets mounted as group-1000 become
# unreadable ("permission denied"). See alxleo/docker-images#143 and the
# pihole-exporter follow-up.
#
# Enforcement: require `USER <name>` (not numeric) OR require a
# preceding addgroup/adduser/useradd in the same Dockerfile.

set -eu

fail=0
for f in "$@"; do
    # Strip comments, find USER lines
    user_lines=$(grep -nE '^[[:space:]]*USER[[:space:]]+' "$f" || true)
    [ -z "$user_lines" ] && continue

    while IFS= read -r line; do
        lineno=$(echo "$line" | cut -d: -f1)
        user_value=$(echo "$line" | cut -d: -f2- | sed -E 's/^[[:space:]]*USER[[:space:]]+//' | awk '{print $1}')

        # Named user — assumed OK (base image provides it, or earlier RUN created it)
        case "$user_value" in
            *[!0-9]*) continue ;;
        esac

        # Numeric user — require addgroup/adduser/useradd earlier in the file
        preamble=$(head -n "$lineno" "$f")
        if echo "$preamble" | grep -qE '^[[:space:]]*RUN[[:space:]].*(addgroup|adduser|useradd|groupadd)'; then
            continue
        fi

        echo "$f:$lineno — numeric USER $user_value without a preceding addgroup/adduser/useradd"
        echo "  Fix: either add 'RUN addgroup -g $user_value app && adduser -u $user_value -G app -S -D app' and USER app,"
        echo "  or use a base image that provides the user (e.g. node:*-alpine has 'node' uid=1000) and 'USER <name>'."
        fail=1
    done <<EOF
$user_lines
EOF
done

exit $fail
