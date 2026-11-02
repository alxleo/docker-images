# syntax=docker/dockerfile:1.7
# One pinned proxy image for the native Helm and workstation deployments.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"
FROM ghcr.io/berriai/litellm:1.106.6@sha256:37e2dafb088a7723beb998590682957386dfc83ffea1848486f8e0e5cfac0b06

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

# The upstream base pins these APK versions in /etc/apk/world, so ordinary
# apk upgrade retains them: https://github.com/BerriAI/litellm/issues/47904.
# These proxy deployments do not use the separately bundled AI admin agent.
# conftest:exempt=user_required -- upstream Prisma client generation requires its existing /app permissions
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    apk add --no-cache --upgrade \
        "ca-certificates-bundle>=20260909-r3" \
        "glibc-2.44>=2.44-r8" \
        "glibc-2.44-locale-posix>=2.44-r8" \
        "ld-linux-2.44>=2.44-r8" \
        "libcrypt1-2.44>=2.44-r8" \
    && apk upgrade --no-cache \
    && rm -rf /opt/liteadmin \
    && uv pip install --python /app/.venv/bin/python --upgrade \
        "certifi==2026.10.23" \
        "PyJWT==2.15.1" \
        "aiohttp==3.14.5" \
        "pypdf==6.21.4" \
        "opentelemetry-api==1.45.2" \
        "opentelemetry-sdk==1.45.2" \
        "opentelemetry-exporter-otlp==1.45.2" \
        "opentelemetry-instrumentation==0.66b2" \
        "opentelemetry-instrumentation-fastapi==0.66b2" \
        "opentelemetry-instrumentation-asgi==0.66b2" \
        "protobuf>=5.29.5,<6" \
    && uv pip check --python /app/.venv/bin/python
