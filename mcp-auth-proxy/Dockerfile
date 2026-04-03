# mcp-auth-proxy -- patched build for VARCHAR(255) fix
#
# Upstream: sigbit/mcp-auth-proxy v2.5.3
# Bug: sigbit/mcp-auth-proxy#111 -- GORM size:255 truncates OAuth token signatures
# Fix: size:255 -> size:512 in pkg/repository/sql.go (7 fields)
#
# Remove when: upstream merges a fix for #111, then switch back to ghcr.io/sigbit/

FROM ghcr.io/alxleo/base-images/golang:1.25-bookworm AS builder

ARG MCP_AUTH_PROXY_VERSION=v2.5.3

WORKDIR /src
RUN git clone --branch ${MCP_AUTH_PROXY_VERSION} --depth 1 https://github.com/sigbit/mcp-auth-proxy.git .

# Fix VARCHAR(255) -- sigbit/mcp-auth-proxy#111
# OAuth token signatures regularly exceed 255 chars (~420 observed)
RUN sed -i 's/size:255/size:512/g' pkg/repository/sql.go

RUN CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /usr/local/bin/mcp-auth-proxy .

# Create data dir in builder (distroless has no mkdir)
RUN mkdir -p /data && chown 65534:65534 /data

# conftest:exempt=healthcheck_required -- proxied behind caddy
FROM gcr.io/distroless/static-debian12:nonroot
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images
COPY --from=builder /usr/local/bin/mcp-auth-proxy /usr/local/bin/mcp-auth-proxy
COPY --from=builder /data /data
ENV DATA_PATH=/data

USER nonroot

ENTRYPOINT ["/usr/local/bin/mcp-auth-proxy"]
