# syntax=docker/dockerfile:1.7
# One pinned proxy image for the native Helm and workstation deployments.
FROM ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b AS uv
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"
FROM ghcr.io/berriai/litellm:1.106.2@sha256:7294b90f868c5c38c99b83021c7ba46f9b439e95f8e32964c925c7d2563a03f7

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
        "certifi==2026.10.19" \
        "PyJWT==2.15.0" \
        "aiohttp==3.14.4" \
        "pypdf==6.21.1" \
        "opentelemetry-api==1.45.1" \
        "opentelemetry-sdk==1.45.1" \
        "opentelemetry-exporter-otlp==1.45.1" \
        "opentelemetry-instrumentation==0.66b1" \
        "opentelemetry-instrumentation-fastapi==0.66b1" \
        "opentelemetry-instrumentation-asgi==0.66b1" \
        "protobuf>=5.29.5,<6" \
    && uv pip check --python /app/.venv/bin/python

# Budget groups must also recognize Git-owned configuration deployments.
# The temporary patch tool does not remain in the runtime image.
RUN --mount=type=bind,source=model-access-groups.patch,target=/tmp/model-access-groups.patch \
    apk add --no-cache --virtual .model-access-groups-build "patch>=2.8" \
    && patch --batch --forward -p1 \
        -d "$(/app/.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
        -i /tmp/model-access-groups.patch \
    && apk del .model-access-groups-build
