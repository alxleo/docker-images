#!/usr/bin/env bash
# Select shared-MCP and full-stack E2E pipelines from exact changed paths.
set -euo pipefail

CHANGED_FILES_JSON="${1:?Usage: $0 <changed-files-json> [ci-changed]}"
CI_CHANGED="${2:-false}"

if [[ "$CI_CHANGED" == "true" ]]; then
    jq -cn '{mcp:true,e2e:true}'
    exit 0
fi

mcp=false
e2e=false
changed_paths=$(jq -er 'if type == "array" then .[] else error("expected an array") end' <<<"$CHANGED_FILES_JSON")
if [[ -n "$changed_paths" ]]; then
    while IFS= read -r path; do
        case "$path" in
        mcp/* | mcp-contracts/* | mcp-images.json | mcp-defaults.json | \
            scripts/mcp-contract.py | test/run-mcp-image-smoke.sh | \
            test/test-mcp-smoke.sh | test/test_entrypoint.py | \
            test/test_mcp_contract.py | test/test_mcp_stack.py | \
            test/test_tool_filtering.py)
            mcp=true
            ;;
        *) ;;
        esac
        case "$path" in
        mcp/* | mcp-images.json | mcp-defaults.json | caddy-cloudflare/* | \
            test/Caddyfile.mcp-e2e | test/docker-compose.mcp-e2e.yml | \
            test/test-mcp-e2e.sh)
            e2e=true
            ;;
        *) ;;
        esac
    done <<<"$changed_paths"
fi

jq -cn --argjson mcp "$mcp" --argjson e2e "$e2e" '{mcp:$mcp,e2e:$e2e}'
