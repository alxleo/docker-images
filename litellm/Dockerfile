# syntax=docker/dockerfile:1.28
# Official signed Docker Hub mirror; publishing remains ghcr.io/alxleo/litellm.
FROM docker.io/litellm/litellm:v1.109.1@sha256:11175975a3093e05e92faee2fe2fe3412a3ae2fcaa849eb0fe25d5f0d8bcb2e9

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

# Discovery still lists uncallable doubled IDs and drops configured URL prefixes.
# Wildcard tracking: https://github.com/BerriAI/litellm/issues/46384.
# Provider fixes also live in https://github.com/mossquartz731/litellm.
# MCP REST defers request hooks to tool admission to avoid acquiring two slots.
# Explicit base_model pricing must also win over an upstream zero-cost receipt.
# Retire each patch when an official release passes the native image checks.
COPY --link *.patch /tmp/litellm-patches/
# conftest:exempt=user_required -- upstream Prisma client generation requires its existing /app permissions
RUN apk add --no-cache --virtual .wildcard-patch patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/wildcard-prefix.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/provider-discovery-path.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/budget-pricing-identity.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/mcp-rest-admission.patch \
    && rm -rf /tmp/litellm-patches \
    && apk del .wildcard-patch
