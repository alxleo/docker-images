#!/usr/bin/env bash
set -euo pipefail

matrix_json="${1:?Usage: $0 <matrix-json> <changed-files-json> <ci-changed>}"
changed_files_json="${2:?Usage: $0 <matrix-json> <changed-files-json> <ci-changed>}"
ci_changed="${3:?Usage: $0 <matrix-json> <changed-files-json> <ci-changed>}"

jq -c \
    --argjson changed "$changed_files_json" \
    --arg ci_changed "$ci_changed" \
    '
        if $ci_changed == "true" then
            .
        else
            [
                .[] |
                . as $image |
                select(
                    any(
                        $changed[];
                        . == $image.context or startswith($image.context + "/")
                    ) or
                    any(
                        ($image.watch_paths // [])[];
                        (
                            sub("^\\./"; "") |
                            sub("/+$"; "")
                        ) as $watch |
                            any(
                                $changed[];
                                . == $watch or startswith($watch + "/")
                            )
                    )
                )
            ]
        end
    ' <<<"$matrix_json"
