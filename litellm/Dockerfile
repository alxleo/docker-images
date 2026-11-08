# syntax=docker/dockerfile:1.28
# One pinned proxy image for the native Helm and workstation deployments.
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"
FROM ghcr.io/berriai/litellm:v1.108.3@sha256:f14d0a035d84d1a8bc98538faf5999e456641fd4cfa191822fd4be1934c1f4f6

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

# The upstream base pins these APK versions in /etc/apk/world, so ordinary
# apk upgrade retains them: https://github.com/BerriAI/litellm/issues/47904.
# These proxy deployments do not use the separately bundled AI admin agent,
# but the package stays installed so /admin/mcp (enterprise-gated via
# LITELLM_ENABLE_ADMIN_MCP) remains available. Its metadata pins mcp==2.2.0
# while the venv ships mcp 2.3.0 — upstream's own lock override runs that
# pair deliberately (https://github.com/BerriAI/litellm/pull/47034) and the
# pin is stale on liteadmin-mcp main too — so align the stale pin before
# the check. The grep makes a no-op sed (upstream fixed the pin) fail this
# build, which is the signal to delete the workaround.
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
    && admin_meta=$(ls /app/.venv/lib/python3.*/site-packages/litellm_admin_mcp-*.dist-info/METADATA) \
    && sed -E -i 's/^Requires-Dist: mcp ?== ?2\.2\.0/Requires-Dist: mcp>=2.2.0,<3/' "$admin_meta" \
    && grep -q 'Requires-Dist: mcp>=2.2.0,<3' "$admin_meta" \
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
