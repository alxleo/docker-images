#!/bin/sh
# Fail pre-commit if a Dockerfile declares `USER <numeric>` without either
# (a) creating a matching group/user earlier in the same build stage, or
# (b) switching to a named user that the base image is known to provide.
#
# Background: `python:3.13-alpine` and `alpine:*` bases do NOT ship a
# user at uid=1000. `USER 1000` on those bases makes the process run
# with gid=0 (root), and Docker secrets mounted as group-1000 become
# unreadable ("permission denied"). See alxleo/docker-images#143 and the
# pihole-exporter follow-up (#144).
#
# Enforcement:
#   - `USER <name>` is always accepted (named user — intent is explicit).
#   - `USER <uid>` or `USER <uid>:<gid>` must be preceded by an addgroup/
#     adduser/useradd/groupadd RUN statement in the SAME build stage.
#
#   - `USER 0` / `USER 0:0` is accepted: root and its group always exist.
#
# Build-stage scope: a `FROM` line starts a new stage; user/group created
# in an earlier stage does not carry into a later one. The scanner resets
# its "saw addgroup?" flag on each FROM.
#
# Instructions are matched on logical lines: `\`-continued physical lines
# are joined first (comment lines inside a continuation are dropped, as the
# Dockerfile parser does), so `RUN apt-get ... \ && addgroup ...` counts.

set -eu

fail=0
for f in "$@"; do
    # Early exit if the file has no USER directive at all.
    if ! grep -qE '^[[:space:]]*USER[[:space:]]+' "$f"; then
        continue
    fi

    # Single forward pass through the file. Track whether we've seen a
    # user-creation RUN in the current stage; reset on each FROM.
    saw_addgroup=0
    lineno=0
    logical=""
    start=0
    while IFS= read -r physical || [ -n "$physical" ]; do
        lineno=$((lineno + 1))

        # A comment is a line whose first non-blank character is `#`. It is
        # never continued, and inside a continuation it is dropped.
        trimmed="${physical#"${physical%%[![:space:]]*}"}"
        case "$trimmed" in
        \#*) continue ;;
        *) ;;
        esac
        if [ -z "$logical" ]; then
            start=$lineno
        fi
        case "$physical" in
        *\\)
            logical="$logical${physical%\\} "
            continue
            ;;
        *) ;;
        esac
        raw_line="$logical$physical"
        raw_line="${raw_line#"${raw_line%%[![:space:]]*}"}"
        logical=""

        case "$raw_line" in
        FROM\ *)
            saw_addgroup=0
            continue
            ;;
        RUN\ *)
            case "$raw_line" in
            *addgroup* | *adduser* | *useradd* | *groupadd*)
                saw_addgroup=1
                ;;
            *) ;;
            esac
            continue
            ;;
        USER\ *)
            # Parse out the user spec; handle both `USER uid` and `USER uid:gid`.
            user_spec=$(printf '%s\n' "$raw_line" | sed -E 's/^[[:space:]]*USER[[:space:]]+//' | awk '{print $1}')
            user_part=${user_spec%%:*}

            # Named user (contains any non-digit) — always accepted.
            # uid 0 is root, whose group always exists.
            case "$user_part" in
            "" | *[!0-9]* | 0)
                continue
                ;;
            *) ;;
            esac

            # Numeric uid — require a preceding group/user creation in THIS stage.
            if [ "$saw_addgroup" = 1 ]; then
                continue
            fi

            # shellcheck disable=SC2016  # backticks in format strings are literal display, not command substitution
            printf '%s:%s — numeric USER %s without a preceding addgroup/adduser/useradd in this build stage\n' "$f" "$start" "$user_spec"
            # shellcheck disable=SC2016
            printf '  Fix: add `RUN addgroup -g %s app && adduser -u %s -G app -S -D app` and `USER app`,\n' "$user_part" "$user_part"
            # shellcheck disable=SC2016
            printf '  or switch to a base image that provides the user (node:*-alpine ships `node` at uid=1000) and use `USER <name>`.\n'
            fail=1
            ;;
        *) ;; # anything else — ignore
        esac
    done <"$f"
done

exit $fail
