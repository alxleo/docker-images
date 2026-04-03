# mcp-substack — read paid Substack subscription content as markdown
#
# Custom MCP server wrapping substack-api. Uses mcp-proxy for HTTP transport.
#
# Secrets (Docker secrets → /run/secrets/ → env vars):
#   SUBSTACK_EMAIL: account email for login
#   SUBSTACK_PASSWORD: account password for login
#   SUBSTACK_USERNAME: Substack profile handle (for listing subscriptions)
#
# Paid content: delegates to crawl4ai (same Docker network) for JS rendering.

# Stage 1: Install uv
FROM ghcr.io/alxleo/base-images/python:3.13-slim AS build
RUN pip install --no-cache-dir uv==0.11.2

# Stage 2: Runtime
FROM ghcr.io/alxleo/base-images/python:3.13-slim
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

# Healthcheck binary: 75KB static C/musl, localhost-only by design
COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

# Install Node.js for mcp-proxy (HTTP bridge)
ARG MCP_PROXY_VERSION=6.4.2
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    npm install -g mcp-proxy@${MCP_PROXY_VERSION} && \
    apt-get purge -y npm && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy uv from build stage
COPY --from=build /usr/local/bin/uv /usr/local/bin/uv

# Install Python dependencies
RUN uv pip install --system --break-system-packages \
    "substack-api>=1.2.0" \
    "markdownify>=0.14.1" \
    "mcp[cli]>=1.9.0"

# Copy server code
COPY server.py /app/server.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENV MCP_PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:8080/ping"]

USER 1000

ENTRYPOINT ["/entrypoint.sh"]
