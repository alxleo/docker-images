# syntax=docker/dockerfile:1.28
# Official signed Docker Hub mirror; publishing remains ghcr.io/alxleo/litellm.
FROM docker.io/litellm/litellm:v1.108.4@sha256:17921779153960f086e2660994cc398fc76ed65c531765177803b9ae0a25d97a

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

# Discovery still lists uncallable doubled IDs and drops configured URL prefixes.
# Wildcard tracking: https://github.com/BerriAI/litellm/issues/46384.
# Local fixes stay in https://github.com/mossquartz731/litellm.
# Retire each patch when an official release passes the native image checks.
COPY --link *.patch /tmp/litellm-patches/
# conftest:exempt=user_required -- upstream Prisma client generation requires its existing /app permissions
RUN apk add --no-cache --virtual .wildcard-patch patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/wildcard-prefix.patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.13/site-packages --strip=1 < /tmp/litellm-patches/provider-discovery-path.patch \
    && rm -rf /tmp/litellm-patches \
    && apk del .wildcard-patch
