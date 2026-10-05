#!/bin/sh
set -eu

mode="${1:-api}"
export FINROBOT_MODE="$mode"
case "$mode" in
    api)
        exec uvicorn finrobot.server:app \
            --host "${FINROBOT_API_HOST:-0.0.0.0}" \
            --port "${FINROBOT_API_PORT:-8000}"
        ;;
    mcp)
        exec python3 /app/finrobot_mcp.py
        ;;
    *)
        echo "usage: finrobot-entrypoint [api|mcp]" >&2
        exit 2
        ;;
esac
