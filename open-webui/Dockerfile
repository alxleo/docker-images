# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"
FROM ghcr.io/open-webui/open-webui:v0.13.0-slim@sha256:283efb20756785229a388bcd1e56a052f5284ae8c861717eed5eaaa3bba6b20a
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
        "mcp==2.3.0" \
        "Pillow==13.0.0" \
        "Mako==1.4.3" \
        "black==26.10.1" \
        "jaraco.context==6.1.2" \
        "setuptools==84.2.1" \
        "urllib3==2.8.0" \
        "msgpack==1.2.4" \
        "wheel==0.48.0" \
        "pip==26.2.2" \
        "opentelemetry-api==1.45.2" \
        "opentelemetry-sdk==1.45.2" \
        "opentelemetry-exporter-otlp==1.45.2" \
        "opentelemetry-instrumentation==0.66b2" \
        "opentelemetry-instrumentation-asgi==0.66b2" \
        "opentelemetry-instrumentation-fastapi==0.66b2" \
        "opentelemetry-instrumentation-logging==0.66b2" \
        "opentelemetry-instrumentation-httpx==0.66b2" \
        "opentelemetry-instrumentation-redis==0.66b2" \
        "opentelemetry-instrumentation-requests==0.66b2" \
        "opentelemetry-instrumentation-sqlalchemy==0.66b2" \
        "opentelemetry-instrumentation-system-metrics==0.66b2" \
        "opentelemetry-instrumentation-aiohttp-client==0.66b2" \
        "protobuf>=5.29.5,<6" \
    && uv pip check --system
