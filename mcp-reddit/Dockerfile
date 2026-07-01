# mcp-reddit -- Reddit reads via the Arctic-Shift archive (no Reddit API credentials)
#
# Replaces the npm reddit-mcp-server image: Reddit's Responsible Builder Policy
# (Nov 2025) closed self-serve OAuth credentials, so the OAuth backend is dead
# (401 on all grants; unauthenticated .json is 403 since 2026-05-30).
# Arctic-Shift (arctic-shift.photon-reddit.com) is a free, no-auth,
# near-real-time archive with full comment trees. Custom FastMCP server
# behind mcp-proxy for HTTP transport. Read-only; no secrets required.

# Stage 1: Install uv
FROM ghcr.io/alxleo/base-images/python:3.13-alpine AS build
RUN pip install --no-cache-dir uv==0.11.2

# Stage 2: Runtime
FROM ghcr.io/alxleo/base-images/python:3.13-alpine
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

# Healthcheck binary: 75KB static C/musl, localhost-only by design
COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

# Install Node.js for mcp-proxy (HTTP bridge)
ARG MCP_PROXY_VERSION=6.4.2
RUN apk add --no-cache nodejs npm \
    && npm install -g mcp-proxy@${MCP_PROXY_VERSION} \
    && apk del npm

# Copy uv from build stage
COPY --from=build /usr/local/bin/uv /usr/local/bin/uv

# Install Python dependencies
RUN uv pip install --system --break-system-packages \
    "mcp[cli]>=1.9.0" \
    "httpx>=0.27"

# Copy server code
COPY server.py /app/server.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENV MCP_PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:8080/ping"]

# Matching uid=1000/gid=1000 app user (base python:alpine ships none — see mcp-substack)
RUN addgroup -g 1000 -S app \
    && adduser -u 1000 -G app -S -D -s /sbin/nologin app
USER app

ENTRYPOINT ["/entrypoint.sh"]
