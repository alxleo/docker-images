# Git MCP Server — @cyanheads/git-mcp-server with native HTTP transport
#
# Speaks streamable HTTP directly (no mcp-proxy wrapper needed).
# Manages git repos on a mounted volume; other services mount it read-only.
#
# Required env vars at runtime:
#   GIT_BASE_DIR=/data   (sandbox all operations to this path)
#   MCP_TRANSPORT_TYPE=http
#   MCP_HTTP_PORT=8080
#   MCP_HTTP_HOST=0.0.0.0
#
# Docker secrets: /run/secrets/git_token → GIT_TOKEN (for private repo cloning)

FROM ghcr.io/alxleo/base-images/node:24-slim
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

# Git + SSH for clone/pull operations, openssh-client for SSH-based remotes
RUN apt-get update && \
    apt-get install -y --no-install-recommends git openssh-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Healthcheck binary (75KB, localhost-only)
COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

# Install the MCP server globally
ARG GIT_MCP_VERSION=2.10.5
RUN npm install -g @cyanheads/git-mcp-server@${GIT_MCP_VERSION}

# Create data directory (owned by non-root user for USER 1000)
RUN mkdir -p /data && chown 1000:1000 /data

# Entrypoint reads Docker secrets into env vars, then starts the server
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

ENV MCP_TRANSPORT_TYPE=http \
    MCP_HTTP_PORT=8080 \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_LOG_LEVEL=info \
    GIT_BASE_DIR=/data

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:8080/ping"]

USER 1000

ENTRYPOINT ["/entrypoint.sh"]
