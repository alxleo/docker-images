# Runtime-only image for the private homelab observer MCP. The private source
# is mounted read-only by the homelab deployment and is never copied here.
ARG UV_VERSION=0.12.7

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM ghcr.io/alxleo/base-images/python:3.14-alpine
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

COPY --from=uv /uv /usr/local/bin/uv
COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

RUN addgroup -g 10001 observer \
    && adduser -D -H -u 10001 -G observer observer \
    && uv pip install --system --break-system-packages \
      "mcp==1.26.0" \
      "pexpect==4.9.0" \
      "pydantic==2.12.5" \
      "PyYAML==6.0.3" \
      "requests==2.32.5" \
      "typer==0.27.0" \
    && rm -rf /root/.cache

WORKDIR /app
ENV PYTHONPATH=/app/src \
    MCP_PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:8080/healthz"]

USER 10001:10001
CMD ["python", "/app/services/mcp-homelab-observer/server.py"]
