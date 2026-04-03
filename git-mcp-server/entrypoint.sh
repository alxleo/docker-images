#!/bin/sh
# Read Docker secrets into environment variables.
# Secret files are mounted at /run/secrets/<name> by Docker Compose.
if [ -d /run/secrets ]; then
    for f in /run/secrets/*; do
        if [ -f "$f" ]; then
            varname=$(basename "$f" | tr '[:lower:]' '[:upper:]')
            export "$varname=$(cat "$f")"
        fi
    done
fi

# Configure git credential helpers for private repo cloning.
#
# Limitation: git's url.insteadOf is global — all clones to a given forge
# use the same identity. If you need per-repo credentials, you'll need
# a git credential helper instead of insteadOf rewrites.
#
# GitHub: fine-grained PAT with Contents: Read-only scope
if [ -n "$SERENA_GITHUB_GIT_TOKEN" ]; then
    git config --global url."https://${SERENA_GITHUB_GIT_TOKEN}@github.com/".insteadOf "https://github.com/"
fi

# GitLab: PAT with read_repository scope
if [ -n "$SERENA_GITLAB_GITLAB_TOKEN" ]; then
    git config --global url."https://oauth2:${SERENA_GITLAB_GITLAB_TOKEN}@gitlab.com/".insteadOf "https://gitlab.com/"
fi

exec git-mcp-server
