# mcp-reddit -- Reddit reads via the Arctic-Shift archive (no Reddit API credentials)
#
# Replaces the npm reddit-mcp-server image: Reddit's Responsible Builder Policy
# (Nov 2025) closed self-serve OAuth credentials, so the OAuth backend is dead
# (401 on all grants; unauthenticated .json is 403 since 2026-05-30).
# Arctic-Shift (arctic-shift.photon-reddit.com) is a free, no-auth,
# near-real-time archive with full comment trees. The server exposes native
# Streamable HTTP. Read-only; no secrets required.

# Stage 1: resolve the locked Python 3.14 environment.
FROM ghcr.io/alxleo/base-images/python:3.14-alpine AS build
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.0
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2: Runtime
FROM ghcr.io/alxleo/base-images/python:3.14-alpine
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ENV PATH="/app/.venv/bin:${PATH}"
COPY --from=build /app/.venv /app/.venv

# Copy server code
COPY server.py /app/server.py
COPY healthcheck.py /app/healthcheck.py

EXPOSE 8080
ENV MCP_PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

# Matching uid=1000/gid=1000 app user (base python:alpine ships none — see mcp-substack)
RUN addgroup -g 1000 -S app \
    && adduser -u 1000 -G app -S -D -s /sbin/nologin app
USER 1000

ENTRYPOINT ["python", "/app/server.py"]
