# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b AS uv
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"
FROM ghcr.io/open-webui/open-webui:v0.11.4-slim@sha256:0487ad4a5a4b986062dedace806c3ef1e88fec38c10d1e64d6a5501c66671e5e
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

# Preserve the application release while refreshing its runtime security dependencies.
# conftest:exempt=user_required -- preserve upstream startup identity; deployments own their UID
# hadolint ignore=DL3005
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    apt-get update \
    && apt-get upgrade --no-install-recommends -y \
    && rm -rf /var/lib/apt/lists/* \
    && uv pip install --system --upgrade \
        "certifi==2026.10.23" \
        "PyJWT==2.15.1" \
        "aiohttp==3.14.5" \
        "cryptography==50.0.2" \
        "mcp==1.30.0" \
        "Pillow==13.0.0" \
        "Mako==1.4.2" \
        "black==26.10.1" \
        "jaraco.context==6.1.2" \
        "setuptools==84.2.1" \
        "urllib3==2.8.0" \
        "msgpack==1.2.3" \
        "wheel==0.46.2" \
        "pip==26.2.2" \
        "opentelemetry-api==1.45.1" \
        "opentelemetry-sdk==1.45.1" \
        "opentelemetry-exporter-otlp==1.45.1" \
        "opentelemetry-instrumentation==0.66b1" \
        "opentelemetry-instrumentation-asgi==0.66b1" \
        "opentelemetry-instrumentation-fastapi==0.66b1" \
        "opentelemetry-instrumentation-logging==0.66b1" \
        "opentelemetry-instrumentation-httpx==0.66b1" \
        "opentelemetry-instrumentation-redis==0.66b1" \
        "opentelemetry-instrumentation-requests==0.66b1" \
        "opentelemetry-instrumentation-sqlalchemy==0.66b1" \
        "opentelemetry-instrumentation-system-metrics==0.66b1" \
        "opentelemetry-instrumentation-aiohttp-client==0.66b1" \
        "protobuf>=5.29.5,<6" \
    && uv pip check --system
