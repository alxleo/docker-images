# syntax=docker/dockerfile:1.28
# Official signed Docker Hub mirror; publishing remains ghcr.io/alxleo/litellm.
FROM docker.io/litellm/litellm:v1.108.5@sha256:008a5916c0a0ca6f4f6ad64969f6a4ef6f03ce885a639f3d97fd53665754ce48

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

# Discovery still lists uncallable doubled IDs and drops configured URL prefixes.
# Wildcard tracking: https://github.com/BerriAI/litellm/issues/46384.
# Provider fixes also live in https://github.com/mossquartz731/litellm.
# MCP REST defers request hooks to tool admission to avoid acquiring two slots.
# Explicit base_model pricing must also win over an upstream zero-cost receipt.
# Notification setup shares caller-scoped snapshots and runs independent reads concurrently.
# Model discovery keeps offline providers off the API loop and uses a short metadata timeout.
# Retire each patch when an official release passes the native image checks.
COPY --link *.patch /tmp/litellm-patches/
# Retire the package overlay when upstream supplies both security fixes.
COPY --link requirements.txt /tmp/litellm-security-requirements.txt
# conftest:exempt=user_required -- upstream Prisma client generation requires its existing /app permissions
RUN apk add --no-cache --virtual .wildcard-patch patch \
    && apk add --no-cache --upgrade 'nodejs-26>=26.13.1-r0' \
    && /app/.venv/bin/python -m ensurepip \
    && /app/.venv/bin/python -m pip install --no-cache-dir --no-deps -r /tmp/litellm-security-requirements.txt \
    && /app/.venv/bin/python -m pip uninstall --yes pip \
    && rm /tmp/litellm-security-requirements.txt \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/wildcard-prefix.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/provider-discovery-path.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/model-discovery-bounds.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/budget-pricing-identity.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/mcp-rest-admission.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/mcp-discovery-initialization.patch \
    && rm -rf /tmp/litellm-patches \
    && apk del .wildcard-patch
