# mcp-auth-proxy — patched build for VARCHAR(255) fix
#
# Upstream: sigbit/mcp-auth-proxy v2.5.3
# Bug: sigbit/mcp-auth-proxy#111 — GORM size:255 truncates OAuth token signatures
# Fix: size:255 → size:512 in pkg/repository/sql.go (7 fields)
#
# Remove when: upstream merges a fix for #111, then switch back to ghcr.io/sigbit/

FROM ghcr.io/alxleo/base-images/golang:1.25-bookworm AS builder
WORKDIR /src
RUN git clone --branch v2.5.3 --depth 1 https://github.com/sigbit/mcp-auth-proxy.git .

# Fix VARCHAR(255) — sigbit/mcp-auth-proxy#111
# OAuth token signatures regularly exceed 255 chars (~420 observed)
RUN sed -i 's/size:255/size:512/g' pkg/repository/sql.go

RUN CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /usr/local/bin/mcp-auth-proxy .

FROM ghcr.io/alxleo/base-images/debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bin/mcp-auth-proxy /usr/local/bin/mcp-auth-proxy
ENV DATA_PATH=/data
ENTRYPOINT ["/usr/local/bin/mcp-auth-proxy"]
