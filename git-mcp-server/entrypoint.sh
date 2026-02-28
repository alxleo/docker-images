#!/bin/sh
# Read Docker secrets into environment variables
if [ -d /run/secrets ]; then
    for f in /run/secrets/*; do
        if [ -f "$f" ]; then
            varname=$(basename "$f" | tr 'a-z' 'A-Z')
            export "$varname=$(cat "$f")"
        fi
    done
fi

# Configure git to use token for HTTPS cloning (if GIT_TOKEN is set)
if [ -n "$GIT_TOKEN" ]; then
    git config --global url."https://${GIT_TOKEN}@github.com/".insteadOf "https://github.com/"
fi

exec git-mcp-server
