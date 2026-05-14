# Upstream: sigbit/mcp-auth-proxy v2.9.1

FROM ghcr.io/alxleo/base-images/golang:1.25-bookworm AS builder

ARG MCP_AUTH_PROXY_VERSION=v2.9.1

WORKDIR /src
RUN git clone --branch ${MCP_AUTH_PROXY_VERSION} --depth 1 https://github.com/sigbit/mcp-auth-proxy.git .

RUN CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /usr/local/bin/mcp-auth-proxy .

# Create data dir in builder (distroless has no mkdir)
# distroless nonroot UID/GID is 65532
RUN mkdir -p /data && chown 65532:65532 /data

# conftest:exempt=healthcheck_required -- proxied behind caddy
FROM gcr.io/distroless/static-debian12:nonroot
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images
COPY --from=builder /usr/local/bin/mcp-auth-proxy /usr/local/bin/mcp-auth-proxy
COPY --from=builder /data /data
ENV DATA_PATH=/data

USER nonroot

ENTRYPOINT ["/usr/local/bin/mcp-auth-proxy"]
