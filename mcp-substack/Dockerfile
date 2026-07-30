# mcp-substack -- read paid Substack subscription content as markdown
#
# Custom MCP server wrapping substack-api with native Streamable HTTP transport.
#
# Secrets (Docker secrets -> /run/secrets/ -> env vars):
#   SUBSTACK_EMAIL: account email for login
#   SUBSTACK_PASSWORD: account password for login
#   SUBSTACK_USERNAME: Substack profile handle (for listing subscriptions)
#
# Paid content: delegates to crawl4ai (same Docker network) for JS rendering.

# Stage 1: resolve the locked Python 3.14 environment.
FROM ghcr.io/alxleo/base-images/python:3.14-alpine AS build
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.0
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2: Runtime
FROM ghcr.io/alxleo/base-images/python:3.14-alpine
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

# Healthcheck binary: 75KB static C/musl, localhost-only by design
COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

ENV PATH="/app/.venv/bin:${PATH}"
COPY --from=build /app/.venv /app/.venv

# Copy server code
COPY server.py /app/server.py

EXPOSE 8080
ENV MCP_PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:8080/ping"]

# Create a matching uid=1000/gid=1000 app user. The base image here,
# ghcr.io/alxleo/base-images/python:3.14-alpine (derived from upstream
# python:3.14-alpine), doesn't ship one (unlike node:26-alpine), so
# USER 1000 was running with gid=0 (root) and couldn't read Docker secrets
# group-owned by gid=1000. Addresses
# "cat: can't open /run/secrets/substack_*: Permission denied".
RUN addgroup -g 1000 -S app \
    && adduser -u 1000 -G app -S -D -s /sbin/nologin app
USER app

ENTRYPOINT ["python", "/app/server.py"]
